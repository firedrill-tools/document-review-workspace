"""Actual native LangChain/Claude JSON with HTTPX2 controlled HTTP."""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import shutil

import httpx2
import pytest

from document_review.runtime import AgentRuntime
from document_review.store import Workspace

USAGE = {
    "input_tokens": 10,
    "output_tokens": 5,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0,
}


def tool(name, arguments, number=1):
    return {
        "type": "tool_use",
        "id": f"tool_synthetic_{number}",
        "name": name,
        "input": arguments,
    }


def body(calls=None, *, finish=None, number=1):
    return {
        "id": f"msg_synthetic_{number}",
        "type": "message",
        "role": "assistant",
        "model": "claude-synthetic-response",
        "stop_reason": finish
        if finish is not None
        else "tool_use"
        if calls
        else "end_turn",
        "stop_sequence": None,
        "content": calls
        if calls
        else [
            {
                "type": "text",
                "text": "A proposal is available for separate operator review.",
            }
        ],
        "usage": USAGE,
        "unknown_field": {"preserved": True},
    }


class Script(httpx2.AsyncBaseTransport):
    def __init__(self, values):
        self.values = iter(values)
        self.requests = []
        self.closed = False

    async def handle_async_request(self, request):
        self.requests.append(json.loads(request.content))
        value = next(self.values)
        if callable(value):
            value = value()
        if isinstance(value, int):
            return httpx2.Response(
                value,
                json={
                    "error": {
                        "type": "overloaded_error",
                        "message": "Synthetic unavailable",
                    },
                    "usage": USAGE,
                },
                headers={"request-id": "synthetic-failed"},
            )
        if isinstance(value, bytes):
            return httpx2.Response(
                200, content=value, headers={"content-type": "application/json"}
            )
        return httpx2.Response(
            200, json=value, headers={"request-id": "synthetic-request"}
        )

    async def aclose(self):
        self.closed = True


@pytest.fixture
def workspace(tmp_path):
    path = tmp_path / "workspace.json"
    shutil.copyfile(Path(__file__).parents[2] / "fixtures/starter.json", path)
    return Workspace(path)


def runtime(workspace, script, **options):
    return AgentRuntime(
        workspace,
        transport=script,
        model="claude-synthetic",
        key="synthetic-not-a-provider-key",
        **options,
    )


def invoke(workspace, script, **options):
    async def run():
        async with runtime(workspace, script, **options) as app:
            return await app.ainvoke(
                {
                    "messages": [
                        {"role": "user", "content": "Review the overview in doc-101."}
                    ]
                },
                thread_id="thread-test",
                run_id="run-test",
            )

    return asyncio.run(run())


def proposal(number=2):
    return tool(
        "propose_edit",
        {
            "document_id": "doc-101",
            "section_id": "overview",
            "replacement_text": "A concise operations overview.",
            "reason": "Clarify the opening.",
        },
        number,
    )


def test_actual_native_read_proposal_final_keeps_committed_text_untouched(workspace):
    before = workspace.document("doc-101")["document"]
    script = Script(
        [
            body([tool("read_document", {"document_id": "doc-101"})]),
            body([proposal()], number=2),
            body(number=3),
        ]
    )
    result = invoke(workspace, script)
    assert script.closed and len(script.requests) == 3
    assert all(
        request.get("stream") is not True and request["max_tokens"] == 4096
        for request in script.requests
    )
    assert script.requests[0]["tool_choice"]["disable_parallel_tool_use"] is True
    assert workspace.document("doc-101")["document"] == before
    saved = workspace.document("doc-101")["proposals"]
    assert (
        len(saved) == 1
        and saved[0]["status"] == "pending"
        and saved[0]["created_by_run"] == "run-test"
    )
    assert result["actual_effects"] == {
        "created_proposal_ids": [saved[0]["id"]],
        "applied_section_ids": [],
    }
    assert (
        result["reported_usage"]["fields"]
        == {key: value * 3 for key, value in USAGE.items()}
        and result["reported_usage"]["total_tokens"] == 45
    )
    receipt = json.loads(Path(result["receipt_path"]).read_text())
    assert receipt["status"] == "completed" and receipt["provider_observations"][0][
        "body"
    ]["unknown_field"] == {"preserved": True}
    assert (
        receipt["provider_observations"][0]["request_id"] == "synthetic-request"
        and receipt["sdk_observations"][0]["accepted"] is True
    )
    assert (
        "synthetic-not-a-provider-key" not in json.dumps(receipt)
        and Path(result["receipt_path"]).stat().st_mode & 0o777 == 0o600
    )


@pytest.mark.parametrize(
    "finish", ["max_tokens", "pause_turn", "refusal", "end_turn", "absent"]
)
def test_unfinished_or_inconsistent_native_tool_does_not_dispatch(workspace, finish):
    reply = body([proposal(1)], finish=finish)
    if finish == "absent":
        reply.pop("stop_reason")
    script = Script([reply])
    with pytest.raises(Exception) as error:
        invoke(workspace, script)
    assert (
        len(script.requests) == 1
        and script.closed
        and workspace.document("doc-101")["proposals"] == []
    )
    data = error.value.evidence
    assert (
        data["status"] == "failed"
        and data["result"] is None
        and data["provider_observations"][0]["body"] == reply
    )
    assert (
        data["reported_usage"]["fields"] == USAGE
        and data["actual_effects"]["created_proposal_ids"] == []
    )


@pytest.mark.parametrize(
    "kind",
    [
        "unknown-tool",
        "multiple-tools",
        "extra-input",
        "nonstring-input",
        "thinking",
        "empty-final",
        "invalid-json",
        "oversized",
    ],
)
def test_unsupported_native_content_is_rejected_before_application_tools(
    workspace, kind
):
    reply = body([proposal(1)])
    if kind == "unknown-tool":
        reply["content"][0]["name"] = "approve_edit"
    if kind == "multiple-tools":
        reply["content"].append(tool("list_documents", {}, 2))
    if kind == "extra-input":
        reply["content"][0]["input"]["revision"] = True
    if kind == "nonstring-input":
        reply["content"][0]["input"]["replacement_text"] = 9
    if kind == "thinking":
        reply["content"].append({"type": "thinking", "thinking": "Unsupported output"})
    if kind == "empty-final":
        reply = body()
        reply["content"][0]["text"] = ""
    if kind == "invalid-json":
        reply = b"{synthetic invalid JSON"
    if kind == "oversized":
        reply = (json.dumps(reply) + " " * 1048576).encode()
    script = Script([reply])
    with pytest.raises(Exception) as error:
        invoke(workspace, script)
    assert (
        workspace.document("doc-101")["proposals"] == []
        and error.value.evidence["result"] is None
        and script.closed
    )


def test_proposal_without_current_run_read_is_an_error_without_a_write(workspace):
    script = Script([body([proposal(1)]), body(number=2)])
    result = invoke(workspace, script)
    receipt = json.loads(Path(result["receipt_path"]).read_text())
    assert workspace.document("doc-101")["proposals"] == []
    assert (
        "read this exact document" in receipt["tools"][0]["result"]["error"]
        and result["actual_effects"]["created_proposal_ids"] == []
    )


def test_native_503_is_one_attempt_with_failed_usage_and_no_proposal(workspace):
    script = Script([503])
    with pytest.raises(Exception) as error:
        invoke(workspace, script)
    assert (
        script.closed
        and len(script.requests) == 1
        and error.value.evidence["reported_usage"]["fields"] == USAGE
    )
    assert error.value.evidence["provider_observations"][0]["http_status"] == 503


@pytest.mark.parametrize("kind", ["missing", "zero", "partial", "invalid"])
def test_raw_usage_is_independent_of_sdk_defaults(workspace, kind):
    reply = body()
    if kind == "missing":
        reply.pop("usage")
    if kind == "zero":
        reply["usage"] = dict.fromkeys(USAGE, 0)
    if kind == "partial":
        reply["usage"] = {"input_tokens": 7}
    if kind == "invalid":
        reply["usage"] = {
            "input_tokens": True,
            "output_tokens": -1,
            "cache_creation_input_tokens": "0",
            "cache_read_input_tokens": None,
        }
    script = Script([reply])
    try:
        result = invoke(workspace, script)
        data = json.loads(Path(result["receipt_path"]).read_text())
    except Exception as error:
        data = error.evidence
    fields = data["reported_usage"]["fields"]
    if kind in {"missing", "invalid"}:
        assert fields == dict.fromkeys(USAGE)
    if kind == "zero":
        assert fields == dict.fromkeys(USAGE, 0)
    if kind == "partial":
        assert fields == {key: 7 if key == "input_tokens" else None for key in USAGE}
    assert (
        data["provider_observations"][0]["body"] == reply
        and data["reported_usage"]["cost_usd"] is None
    )
