"""Invoke the actual document review API and default AG-UI runtime as local callables."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
from urllib.parse import quote
from uuid import uuid4

import httpx2 as httpx
from document_review.api import create_app


def capture(response):
    try:
        body = response.json()
    except ValueError:
        body = {"text": response.text}
    return {"status": response.status_code, "body": body}


def save(path, value):
    with path.open("xb") as output:
        os.chmod(path, 0o600)
        output.write(value)
        output.flush()
        os.fsync(output.fileno())


def read_events(text):
    events = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        data = "\n".join(line[5:].lstrip(" ") for line in block.splitlines() if line.startswith("data:"))
        if not data or data == "[DONE]":
            continue
        event = json.loads(data)
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            raise ValueError("Application returned an invalid AG-UI event")
        events.append(event)
    return events


async def execute(args):
    chat = args.action == "chat"
    app = create_app(args.workspace, include_agent=chat)
    thread_id, run_id = (str(uuid4()), str(uuid4())) if chat else (None, None)
    if chat:
        save(args.workspace.parent / "application-run.json", json.dumps({"threadId": thread_id, "runId": run_id}).encode())
    result = {"executionKind": "native_agui_request" if chat else "application_state_inspection",
              "threadId": thread_id, "runId": run_id, "http": None, "events": None, "evidence": None}
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://application.local") as client:
            path = "/documents/" + quote(args.record, safe="")
            result["before"] = capture(await client.get(path))
            if result["before"]["status"] != 200:
                raise ValueError("Selected document review record is not available")
            if chat:
                body = {"threadId": thread_id, "runId": run_id, "state": {},
                        "messages": [{"id": str(uuid4()), "role": "user", "content": args.message}],
                        "tools": [], "context": [], "forwardedProps": {}}
                response = await client.post("/agent", json=body, headers={"accept": "text/event-stream"})
                raw = args.workspace.parent / "ag-ui.sse"
                save(raw, response.content)
                result["http"] = {"status": response.status_code, "rawEventsFile": str(raw)}
                result["events"] = read_events(response.text) if response.status_code == 200 else []
                result["evidence"] = capture(await client.get("/runs/" + thread_id + "/" + run_id))
            result["after"] = capture(await client.get(path))
    result["backendRuntimeClosed"] = app.state.runtime.closed if chat else None
    if not chat:
        return result, 0 if result["after"]["status"] == 200 else 1
    events = result["events"]
    completed = (result["http"]["status"] == 200 and result["after"]["status"] == 200
                 and result["evidence"]["status"] == 200 and result["backendRuntimeClosed"] is True
                 and not any(event["type"] == "RUN_ERROR" for event in events)
                 and any(event["type"] == "RUN_FINISHED" and event.get("threadId") == thread_id
                         and event.get("runId") == run_id for event in events))
    return result, 0 if completed else 1


def main():
    parser = argparse.ArgumentParser(description="Invoke the real document review ASGI API or AG-UI agent")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--action", choices=["chat", "inspect"], required=True)
    parser.add_argument("--record", required=True)
    parser.add_argument("--message")
    args = parser.parse_args()
    result, status = asyncio.run(execute(args))
    print(json.dumps(result))
    return status


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, OSError) as error:
        print(json.dumps({"error": str(error), "type": type(error).__name__}), file=sys.stderr)
        raise SystemExit(1)
