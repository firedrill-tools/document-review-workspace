"""Real app/SDKs and test-only controlled Claude HTTP; no live model call."""

import json
from pathlib import Path
import shutil
import httpx2
import uvicorn
from document_review.api import create_app
from document_review.runtime import AgentRuntime

root = Path(__file__).resolve().parents[2]
state = root / "frontend/.e2e/workspace.json"
state.parent.mkdir(exist_ok=True)
shutil.copyfile(root / "fixtures/starter.json", state)
sequence = 0


def handle(request):
    global sequence
    sequence += 1
    body = json.loads(request.content)
    assert request.url.path == "/v1/messages" and body.get("stream") is not True
    pending = set()
    human = []
    results = []
    for index, message in enumerate(body["messages"]):
        content = message["content"]
        parts = (
            [{"type": "text", "text": content}] if isinstance(content, str) else content
        )
        if message["role"] == "assistant":
            pending.update(part["id"] for part in parts if part["type"] == "tool_use")
        else:
            for part in parts:
                if part["type"] == "tool_result":
                    if part["tool_use_id"] not in pending:
                        return httpx2.Response(
                            400,
                            json={
                                "error": {
                                    "type": "invalid_request_error",
                                    "message": "Orphan tool result in controlled conversation",
                                }
                            },
                        )
                    pending.remove(part["tool_use_id"])
                    results.append((index, part))
            text = next(
                (part["text"] for part in reversed(parts) if part["type"] == "text"), ""
            )
            if text:
                if pending:
                    return httpx2.Response(
                        400,
                        json={
                            "error": {
                                "type": "invalid_request_error",
                                "message": "Unanswered tool call before new user turn",
                            }
                        },
                    )
                human.append((index, text))
    if pending:
        return httpx2.Response(
            400,
            json={
                "error": {
                    "type": "invalid_request_error",
                    "message": "Missing controlled tool results",
                }
            },
        )
    start, task = human[-1]
    task = task.lower()
    after = [part for index, part in results if index > start]
    usage = {
        "input_tokens": 40,
        "output_tokens": 15,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    if "provider outage" in task:
        return httpx2.Response(
            503,
            json={
                "error": {
                    "type": "overloaded_error",
                    "message": "Controlled offline provider outage",
                },
                "usage": usage,
            },
        )
    if "unfinished response" in task:
        name, arguments, finish = (
            "propose_edit",
            {
                "document_id": "doc-101",
                "section_id": "overview",
                "replacement_text": "An unfinished replacement must never be saved.",
                "reason": "Controlled unfinished proposal",
            },
            "max_tokens",
        )
    elif not after:
        name, arguments, finish = (
            "read_document",
            {"document_id": "doc-101"},
            "tool_use",
        )
    elif len(after) == 1:
        name, arguments, finish = (
            "propose_edit",
            {
                "document_id": "doc-101",
                "section_id": "overview",
                "replacement_text": "The operations team logs incidents and the incident commander coordinates the response.",
                "reason": "Clarify the overview while preserving the handoff responsibilities.",
            },
            "tool_use",
        )
    else:
        name, arguments, finish = None, None, "end_turn"
    content = (
        [
            {
                "type": "tool_use",
                "id": f"tool_synthetic_{sequence}",
                "name": name,
                "input": arguments,
            }
        ]
        if name
        else [
            {
                "type": "text",
                "text": 'Saved a proposal for doc-101. An operator must approve it; no document text has changed.\n\n<script>window.syntheticUnsafe=1</script><a href="javascript:window.syntheticUnsafe=1">Unsafe link</a>',
            }
        ]
    )
    return httpx2.Response(
        200,
        json={
            "id": f"msg_synthetic_{sequence}",
            "type": "message",
            "role": "assistant",
            "model": "claude-synthetic-response",
            "stop_reason": finish,
            "stop_sequence": None,
            "content": content,
            "usage": usage,
        },
        headers={"request-id": f"synthetic-request-{sequence}"},
    )


app = create_app(
    state,
    runtime_factory=lambda workspace: AgentRuntime(
        workspace,
        model="claude-synthetic",
        key="synthetic-not-a-secret",
        transport=httpx2.MockTransport(handle),
    ),
)
uvicorn.run(app, host="127.0.0.1", port=38124)
