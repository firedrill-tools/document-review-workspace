"""Owned runtime, failure publication, native cancellation and real AG-UI HTTP."""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import shutil

from fastapi.testclient import TestClient
import httpx2
import pytest

from document_review.api import create_app
from document_review.evidence import publish, receipt_path
from document_review.runtime import AgentRuntime
from document_review.store import Conflict
from test_native import Script, body, proposal, runtime, tool, workspace


def test_changed_section_after_native_read_requires_a_fresh_read(workspace):
    def changed():
        saved = workspace.propose(
            "doc-101", "overview", "Changed by the operator.", "Intervening edit"
        )
        workspace.decide(saved["id"], 1, "approve", "human-reviewer")
        return body([proposal()], number=2)

    script = Script(
        [
            body([tool("read_document", {"document_id": "doc-101"})]),
            changed,
            body(number=3),
        ]
    )

    async def exercise():
        async with runtime(workspace, script) as app:
            result = await app.ainvoke(
                {"messages": [{"role": "user", "content": "Review doc-101."}]},
                thread_id="thread-change",
                run_id="run-change",
            )
            assert list(app.checkpointer.list(None)) == []
        assert app.http.is_closed and app.client.is_closed() and app.closed
        return result

    result = asyncio.run(exercise())
    data = json.loads(Path(result["receipt_path"]).read_text())
    assert len(workspace.document("doc-101")["proposals"]) == 1
    assert (
        "section changed" in data["tools"][-1]["result"]["error"]
        and data["actual_effects"]["created_proposal_ids"] == []
    )


@pytest.mark.parametrize("phase", ["request", "response", "before-proposal", "final"])
def test_recording_fault_stops_new_work_and_reports_actual_committed_proposal(
    workspace, phase
):
    script = Script(
        [
            body([tool("read_document", {"document_id": "doc-101"})]),
            body([proposal()], number=2),
            body(number=3),
        ]
    )

    def writer(path, data):
        observations = data["provider_observations"]
        reject = (
            phase == "request"
            and observations
            and observations[-1]["status"] == "prepared"
            or phase == "response"
            and observations
            and observations[-1]["body"] is not None
            or phase == "before-proposal"
            and len(observations) == 2
            and observations[-1]["status"] == "accepted"
            or phase == "final"
            and data["status"] == "completed"
        )
        if reject:
            raise OSError("Synthetic recording failure")
        publish(path, data)

    async def exercise():
        async with runtime(workspace, script, writer=writer) as app:
            with pytest.raises(Exception) as error:
                await app.ainvoke(
                    {"messages": [{"role": "user", "content": "Review doc-101."}]},
                    thread_id="thread-recording",
                    run_id="run-recording",
                )
            assert list(app.checkpointer.list(None)) == []
            return error.value.evidence

    data = asyncio.run(exercise())
    assert data["status"] == "failed" and data["result"] is None and script.closed
    assert len(workspace.document("doc-101")["proposals"]) == (
        1 if phase == "final" else 0
    )
    assert len(data["actual_effects"]["created_proposal_ids"]) == (
        1 if phase == "final" else 0
    )


@pytest.mark.parametrize("kind", ["cancel", "deadline", "shutdown"])
def test_native_cancel_deadline_shutdown_close_owned_work_without_late_proposal(
    workspace, kind
):
    async def exercise():
        entered = asyncio.Event()
        closed = []

        class Pending(httpx2.AsyncBaseTransport):
            async def handle_async_request(self, request):
                entered.set()
                await asyncio.Event().wait()

            async def aclose(self):
                closed.append(True)

        app = runtime(workspace, Pending(), timeout=0.2 if kind == "deadline" else 120)
        await app.__aenter__()
        try:
            task = asyncio.create_task(
                app.ainvoke(
                    {"messages": [{"role": "user", "content": "Review doc-101."}]},
                    thread_id="thread-cancel",
                    run_id="run-cancel",
                )
            )
            await asyncio.wait_for(entered.wait(), 3)
            if kind == "cancel":
                task.cancel()
            if kind == "shutdown":
                await app.__aexit__(None, None, None)
            with pytest.raises(
                TimeoutError if kind == "deadline" else asyncio.CancelledError
            ) as error:
                await task
            assert (
                error.value.evidence["status"] == "failed"
                and error.value.evidence["result"] is None
            )
            assert (
                workspace.document("doc-101")["proposals"] == []
                and list(app.checkpointer.list(None)) == []
            )
        finally:
            if not app.closed:
                await app.__aexit__(None, None, None)
        assert app.closed and app.http.is_closed and closed

    asyncio.run(exercise())


def payload(run_id="agui-run"):
    return {
        "threadId": "agui-thread",
        "runId": run_id,
        "state": {},
        "messages": [
            {
                "id": f"user-{run_id}",
                "role": "user",
                "content": "Review doc-101 overview.",
            }
        ],
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }


def test_actual_agui_http_uses_native_tools_receipt_and_separate_operator_decision(
    workspace,
):
    script = Script(
        [
            body([tool("read_document", {"document_id": "doc-101"})]),
            body([proposal()], number=2),
            body(number=3),
        ]
    )
    app = create_app(
        workspace.path, runtime_factory=lambda state: runtime(state, script)
    )
    with TestClient(app) as client:
        reply = client.post("/agent", json=payload())
        assert (
            reply.status_code == 200
            and "RUN_FINISHED" in reply.text
            and "RUN_ERROR" not in reply.text
        ), reply.text[-1500:]
        saved = client.get("/documents/doc-101").json()["proposals"]
        assert len(saved) == 1 and saved[0]["status"] == "pending"
        receipt = client.get("/runs/agui-thread/agui-run").json()
        assert (
            receipt["status"] == "completed"
            and len(receipt["provider_observations"]) == 3
            and list(app.state.runtime.checkpointer.list(None)) == []
        )
        assert (
            client.post(
                f"/proposals/{saved[0]['id']}/decision",
                json={"revision": 1, "decision": "approve", "actor": "human-reviewer"},
            ).status_code
            == 200
        )
        assert (
            client.get("/documents/doc-101").json()["document"]["sections"][0]["text"]
            == saved[0]["replacement_text"]
        )
        duplicate = client.post("/agent", json=payload())
        assert (
            "RUN_ERROR" in duplicate.text
            and "RUN_FINISHED" not in duplicate.text
            and len(script.requests) == 3
        )
    assert script.closed and app.state.runtime.closed


def test_actual_agui_failure_then_fresh_run_recovers_without_reusing_stale_checkpoints(
    workspace,
):
    script = Script([body([proposal(1)], finish="max_tokens"), body()])
    app = create_app(
        workspace.path, runtime_factory=lambda state: runtime(state, script)
    )
    with TestClient(app) as client:
        failed = client.post("/agent", json=payload("failed"))
        assert "RUN_ERROR" in failed.text and "RUN_FINISHED" not in failed.text
        receipt = client.get("/runs/agui-thread/failed").json()
        assert (
            receipt["status"] == "failed"
            and receipt["result"] is None
            and len(receipt["provider_observations"]) == 1
        )
        recovered = client.post("/agent", json=payload("recovered"))
        assert "RUN_FINISHED" in recovered.text and "RUN_ERROR" not in recovered.text, (
            recovered.text[-1500:]
        )
        assert workspace.document("doc-101")["proposals"] == []
    assert script.closed


def test_deadline_after_temp_write_before_replace_does_not_publish_late_proposal(
    workspace, monkeypatch
):
    from contextlib import contextmanager
    import time
    import document_review.store as module

    original = module.NamedTemporaryFile

    @contextmanager
    def slow_private_temp(*args, **options):
        with original(*args, **options) as file:

            class DelayedFlush:
                def __getattr__(self, name):
                    return getattr(file, name)

                def flush(self):
                    time.sleep(0.15)
                    file.flush()

            yield DelayedFlush()

    monkeypatch.setattr(module, "NamedTemporaryFile", slow_private_temp)
    script = Script(
        [
            body([tool("read_document", {"document_id": "doc-101"})]),
            body([proposal()], number=2),
        ]
    )
    before = workspace.path.read_bytes()

    async def exercise():
        async with runtime(workspace, script, timeout=0.1) as app:
            with pytest.raises(TimeoutError) as error:
                await app.ainvoke(
                    {"messages": [{"role": "user", "content": "Review doc-101."}]},
                    thread_id="thread-late",
                    run_id="run-late",
                )
            assert error.value.evidence["actual_effects"]["created_proposal_ids"] == []

    asyncio.run(exercise())
    assert (
        len(script.requests) == 2
        and script.closed
        and workspace.path.read_bytes() == before
    )
    assert list(workspace.path.parent.glob(".workspace.json.*.tmp")) == []


def test_native_model_budget_and_replayed_tool_id_stop_before_another_dispatch(
    workspace,
):
    async def exercise():
        script = Script(
            [
                body([tool("list_documents", {}, number)], number=number)
                for number in range(1, 10)
            ]
        )
        async with runtime(workspace, script) as app:
            with pytest.raises(Exception) as error:
                await app.ainvoke(
                    {
                        "messages": [
                            {"role": "user", "content": "Keep listing documents."}
                        ]
                    },
                    thread_id="budget-thread",
                    run_id="budget-run",
                )
            assert (
                len(script.requests) <= 8 and error.value.evidence["status"] == "failed"
            )
        repeated = Script(
            [
                body([tool("read_document", {"document_id": "doc-101"}, 1)]),
                body([proposal(1)], number=2),
            ]
        )
        async with runtime(workspace, repeated) as app:
            with pytest.raises(Exception) as error:
                await app.ainvoke(
                    {"messages": [{"role": "user", "content": "Review doc-101."}]},
                    thread_id="replay-thread",
                    run_id="replay-run",
                )
            assert (
                "replayed"
                in error.value.evidence["provider_observations"][-1]["error"]["message"]
                and workspace.document("doc-101")["proposals"] == []
            )

    asyncio.run(exercise())


def test_concurrent_run_refused_before_second_model_and_runtime_can_recover(workspace):
    async def exercise():
        entered = asyncio.Event()
        release = asyncio.Event()
        calls = []

        class Pending(Script):
            async def handle_async_request(self, request):
                calls.append(True)
                if len(calls) == 1:
                    entered.set()
                    await release.wait()
                return httpx2.Response(200, json=body())

        transport = Pending([])
        async with runtime(workspace, transport) as app:
            task = asyncio.create_task(
                app.ainvoke(
                    {"messages": [{"role": "user", "content": "First run."}]},
                    thread_id="first-thread",
                    run_id="first-run",
                )
            )
            await asyncio.wait_for(entered.wait(), 3)
            with pytest.raises(Conflict, match="active run"):
                await app.ainvoke(
                    {"messages": [{"role": "user", "content": "Second run."}]},
                    thread_id="second-thread",
                    run_id="second-run",
                )
            release.set()
            await task
            await app.ainvoke(
                {"messages": [{"role": "user", "content": "Second run."}]},
                thread_id="second-thread",
                run_id="second-run",
            )
            assert len(calls) == 2 and list(app.checkpointer.list(None)) == []

    asyncio.run(exercise())


def test_error_after_proposal_commit_retains_effect_and_new_run_recovers_exact_pending_proposal(
    workspace, monkeypatch
):
    original = workspace.propose

    def uncertain(*args, **options):
        original(*args, **options)
        raise OSError("Synthetic lost acknowledgement after proposal commit")

    monkeypatch.setattr(workspace, "propose", uncertain)
    script = Script(
        [
            body([tool("read_document", {"document_id": "doc-101"})]),
            body([proposal()], number=2),
        ]
    )

    async def exercise():
        async with runtime(workspace, script) as app:
            with pytest.raises(OSError) as error:
                await app.ainvoke(
                    {"messages": [{"role": "user", "content": "Review doc-101."}]},
                    thread_id="uncertain-thread",
                    run_id="uncertain-run",
                )
            assert (
                len(error.value.evidence["actual_effects"]["created_proposal_ids"]) == 1
            )
        monkeypatch.setattr(workspace, "propose", original)
        retry = Script(
            [
                body([tool("read_document", {"document_id": "doc-101"})]),
                body([proposal()], number=2),
                body(number=3),
            ]
        )
        async with runtime(workspace, retry) as app:
            result = await app.ainvoke(
                {"messages": [{"role": "user", "content": "Review doc-101."}]},
                thread_id="recovery-thread",
                run_id="recovery-run",
            )
            data = json.loads(Path(result["receipt_path"]).read_text())
            assert (
                data["tools"][-1]["result"]["proposal_replayed"] is True
                and result["actual_effects"]["created_proposal_ids"] == []
            )

    asyncio.run(exercise())
    assert (
        len(workspace.document("doc-101")["proposals"]) == 1
        and workspace.document("doc-101")["document"]["revision"] == 1
    )


def test_runtime_startup_failure_closes_constructed_native_sdk_and_http(
    workspace, monkeypatch
):
    import document_review.runtime as module

    def fail(*args, **options):
        raise RuntimeError("Synthetic graph startup failure")

    monkeypatch.setattr(module, "build_agent", fail)
    transport = Script([])

    async def exercise():
        app = runtime(workspace, transport)
        with pytest.raises(RuntimeError, match="startup"):
            await app.__aenter__()
        assert (
            app.closed
            and app.http.is_closed
            and app.client.is_closed()
            and transport.closed
        )

    asyncio.run(exercise())
