"""Versioned population integrity, exclusive copies, honest history and native scopes."""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import shutil

import pytest

from document_review.contracts import SAFE_INTEGER, WorkspaceData
from document_review.datasets import (
    data_root,
    initialize_case,
    list_cases,
    load_manifest,
    select_case,
    sha,
)
from document_review.store import Conflict, Workspace
from test_native import Script, body, runtime, tool


@pytest.mark.parametrize("case", list_cases()["cases"], ids=lambda case: case["id"])
def test_every_hash_bound_case_copies_exactly_and_privately_without_invented_model_history(
    tmp_path, case
):
    target = tmp_path / case["id"] / "workspace.json"
    result = initialize_case(case["id"], target)
    raw = target.read_bytes()
    state = Workspace(target).snapshot()["state"]
    assert sha(raw) == case["sha256"] == result["fixture_sha256"]
    assert state["dataset"]["case_id"] == case["id"] and result["task"] == case["task"]
    assert (
        len(state["documents"]) == case["documents"]
        and len(state["proposals"]) == case["proposals"]
    )
    assert all(
        proposal["origin"] == "human_import"
        and proposal["created_by_run"] is None
        and proposal["created_by_thread"] is None
        for proposal in state["proposals"]
    )
    assert (
        target.stat().st_mode & 0o777 == 0o600
        and target.parent.stat().st_mode & 0o777 == 0o700
    )
    with pytest.raises(FileExistsError):
        initialize_case(case["id"], target)
    assert target.read_bytes() == raw
    if case["id"] == "busy":
        assert sum(len(doc["sections"]) for doc in state["documents"]) == 100
        assert len(state["documents"]) == 20 and len(state["proposals"]) == 30
        assert {
            status: sum(item["status"] == status for item in state["proposals"])
            for status in ("approved", "rejected", "pending")
        } == {"approved": 12, "rejected": 8, "pending": 10}


@pytest.mark.parametrize(
    "kind",
    ["hash", "traversal", "symlink", "boolean-version", "wrong-count", "false-trial"],
)
def test_tampered_manifest_case_or_path_cannot_initialize(tmp_path, kind):
    root = tmp_path / "dataset"
    shutil.copytree(data_root(), root)
    manifest = json.loads((root / "manifest.json").read_text())
    entry = next(item for item in manifest["cases"] if item["id"] == "busy")
    target = root / entry["file"]
    if kind == "hash":
        target.write_text(target.read_text() + "\n")
    if kind == "traversal":
        entry["file"] = "../outside.json"
    if kind == "symlink":
        outside = tmp_path / "outside.json"
        outside.write_bytes(target.read_bytes())
        target.unlink()
        target.symlink_to(outside)
    if kind in {"boolean-version", "false-trial"}:
        state = json.loads(target.read_text())
        if kind == "boolean-version":
            state["dataset"]["version"] = True
        else:
            state["proposals"][0].update(
                origin="model_proposal", created_by_run="invented-run"
            )
        target.write_text(json.dumps(state))
        entry["sha256"] = sha(target.read_bytes())
    if kind == "wrong-count":
        entry["approved"] -= 1
        entry["pending"] += 1
    (root / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        initialize_case("busy", tmp_path / "new.json", root)
    assert not (tmp_path / "new.json").exists()


@pytest.mark.parametrize(
    "kind",
    ["conflicting-history", "wrong-current-text", "backwards-time", "non-utc-time"],
)
def test_incoherent_human_history_is_rejected_without_fabricating_repairs(kind):
    _, raw, _ = select_case("busy")
    state = json.loads(raw)
    if kind == "conflicting-history":
        extra = deepcopy(state["proposals"][0])
        extra["id"] = "another-import"
        state["proposals"].append(extra)
    if kind == "wrong-current-text":
        state["documents"][0]["sections"][0]["text"] = (
            "Not the latest approved replacement."
        )
    if kind == "backwards-time":
        state["proposals"][0]["decided_at"] = "2026-10-13T09:00:00Z"
    if kind == "non-utc-time":
        state["proposals"][0]["created_at"] = "2026-10-14T09:00:00"
    with pytest.raises(ValueError):
        WorkspaceData.model_validate(state)


def test_existing_target_symlink_is_refused_without_touching_its_file(tmp_path):
    victim = tmp_path / "kept.json"
    victim.write_text("Existing operator data")
    link = tmp_path / "workspace.json"
    link.symlink_to(victim)
    with pytest.raises(FileExistsError):
        initialize_case("starter", link)
    assert link.is_symlink() and victim.read_text() == "Existing operator data"


def test_revision_exhaustion_and_stale_rejection_preserve_human_history(tmp_path):
    limit = tmp_path / "limit.json"
    initialize_case("revision-limit", limit)
    workspace = Workspace(limit)
    source = workspace.document("doc-101")["document"]
    before = deepcopy(source)
    proposal = workspace.propose(
        "doc-101",
        "overview",
        "Cannot apply this extra revision.",
        "Safe revision boundary probe",
    )
    with pytest.raises(Conflict, match="revision limit"):
        workspace.decide(proposal["id"], 1, "approve", "reviewer")
    assert (
        workspace.document("doc-101")["document"] == before
        and before["revision"] == SAFE_INTEGER
    )
    workspace.decide(proposal["id"], 1, "reject", "reviewer")
    stale = tmp_path / "stale.json"
    initialize_case("stale-competing-edit", stale)
    workspace = Workspace(stale)
    current = workspace.document("doc-101")["document"]
    pending = next(
        item
        for item in workspace.document("doc-101")["proposals"]
        if item["status"] == "pending"
    )
    with pytest.raises(Conflict, match="section changed"):
        workspace.decide(pending["id"], 1, "approve", "reviewer")
    workspace.decide(pending["id"], 1, "reject", "reviewer")
    assert workspace.document("doc-101")["document"] == current


@pytest.mark.parametrize(
    "case_id,target,section_id,replacement",
    [
        (
            "busy",
            "doc-113",
            "overview",
            "The quality review group records verified findings and assigns an owner before handoff.",
        ),
        ("protected-target", "doc-101", "legal", "Shorter protected notice."),
        (
            "already-proposed",
            "doc-101",
            "overview",
            "The operations team logs incidents and the incident commander coordinates the response.",
        ),
    ],
)
def test_actual_native_case_keeps_history_and_reports_only_new_proposal_effects(
    tmp_path, case_id, target, section_id, replacement
):
    path = tmp_path / "workspace.json"
    initialize_case(case_id, path)
    workspace = Workspace(path)
    case, _, _ = select_case(case_id)
    initial = workspace.snapshot()["state"]
    reason = "Clarify the overview while preserving the handoff responsibilities."
    script = Script(
        [
            body([tool("read_document", {"document_id": target})]),
            body(
                [
                    tool(
                        "propose_edit",
                        {
                            "document_id": target,
                            "section_id": section_id,
                            "replacement_text": replacement,
                            "reason": reason,
                        },
                        2,
                    )
                ],
                number=2,
            ),
            body(number=3),
        ]
    )

    async def exercise():
        async with runtime(workspace, script) as app:
            return await app.ainvoke(
                {"messages": [{"role": "user", "content": case.task}]},
                thread_id="case-thread",
                run_id="case-run",
            )

    result = asyncio.run(exercise())
    final = workspace.snapshot()["state"]
    assert final["documents"] == initial["documents"]
    assert final["proposals"][: len(initial["proposals"])] == initial["proposals"]
    expected = 1 if case_id == "busy" else 0
    assert (
        len(final["proposals"]) - len(initial["proposals"]) == expected
        and len(result["actual_effects"]["created_proposal_ids"]) == expected
    )
    receipt = json.loads(Path(result["receipt_path"]).read_text())
    assert (
        case.focus not in json.dumps(script.requests)
        and receipt["initial_state"]["state"]["dataset"]["case_id"] == case_id
    )
    if case_id == "protected-target":
        assert "protected" in receipt["tools"][-1]["result"]["error"]
    if case_id == "already-proposed":
        assert receipt["tools"][-1]["result"]["proposal_replayed"] is True


def test_same_run_name_in_another_native_thread_is_not_attributed_to_the_observer(
    tmp_path,
):
    path = tmp_path / "workspace.json"
    initialize_case("starter", path)
    workspace = Workspace(path)
    other = Script(
        [
            body([tool("read_document", {"document_id": "doc-101"})]),
            body(
                [
                    tool(
                        "propose_edit",
                        {
                            "document_id": "doc-101",
                            "section_id": "overview",
                            "replacement_text": "Another thread owns this proposal.",
                            "reason": "Independent native thread.",
                        },
                        2,
                    )
                ],
                number=2,
            ),
            body(number=3),
        ]
    )

    class Observer(Script):
        async def handle_async_request(self, request):
            async with runtime(workspace, other) as app:
                self.other_result = await app.ainvoke(
                    {"messages": [{"role": "user", "content": "Review doc-101."}]},
                    thread_id="other-thread",
                    run_id="same-run",
                )
            return await super().handle_async_request(request)

    observer = Observer([body()])

    async def exercise():
        async with runtime(workspace, observer) as app:
            return await app.ainvoke(
                {"messages": [{"role": "user", "content": "Explain review rules."}]},
                thread_id="observer-thread",
                run_id="same-run",
            )

    result = asyncio.run(exercise())
    assert (
        result["actual_effects"]["created_proposal_ids"] == []
        and len(observer.other_result["actual_effects"]["created_proposal_ids"]) == 1
    )
    assert (
        workspace.document("doc-101")["proposals"][0]["created_by_thread"]
        == "other-thread"
    )
