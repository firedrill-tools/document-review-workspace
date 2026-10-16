"""Strict operator intent, shared state ownership and atomic publication."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from fastapi.testclient import TestClient
import pytest

from document_review.api import create_app
from document_review.store import Conflict, Workspace


@pytest.fixture
def workspace(tmp_path):
    path = tmp_path / "workspace.json"
    shutil.copyfile(Path(__file__).parents[2] / "fixtures/starter.json", path)
    return Workspace(path)


@pytest.mark.parametrize("revision", [True, 1.0, "1", 0, -1, 2**53])
def test_http_and_direct_decisions_reject_coerced_or_unsafe_revisions(
    workspace, revision
):
    proposal = workspace.propose(
        "doc-101", "overview", "A reviewed replacement.", "Strict revision probe"
    )
    before = workspace.path.read_bytes()
    client = TestClient(create_app(workspace.path, include_agent=False))
    response = client.post(
        f"/proposals/{proposal['id']}/decision",
        json={"revision": revision, "decision": "approve", "actor": "reviewer"},
    )
    assert response.status_code == 422
    with pytest.raises(ValueError, match="revision"):
        workspace.decide(proposal["id"], revision, "approve", "reviewer")
    assert workspace.path.read_bytes() == before


def test_http_unknown_decision_fields_cannot_commit(workspace):
    proposal = workspace.propose(
        "doc-101", "overview", "A reviewed replacement.", "Strict fields probe"
    )
    client = TestClient(create_app(workspace.path, include_agent=False))
    response = client.post(
        f"/proposals/{proposal['id']}/decision",
        json={
            "revision": 1,
            "decision": "approve",
            "actor": "reviewer",
            "replacement_text": "Unreviewed caller input",
        },
    )
    assert (
        response.status_code == 422
        and workspace.document("doc-101")["proposals"][0]["status"] == "pending"
    )


@pytest.mark.parametrize(
    "kind",
    [
        "duplicate-document",
        "duplicate-section",
        "orphan-proposal",
        "boolean-section-revision",
        "false-lock-type",
        "unknown-field",
    ],
)
def test_invalid_loaded_state_fails_before_any_mutation(workspace, kind):
    proposal = workspace.propose(
        "doc-101", "overview", "A reviewed replacement.", "Strict loaded state probe"
    )
    data = json.loads(workspace.path.read_text())
    if kind == "duplicate-document":
        data["documents"].append(deepcopy(data["documents"][0]))
    elif kind == "duplicate-section":
        data["documents"][0]["sections"].append(
            deepcopy(data["documents"][0]["sections"][0])
        )
    elif kind == "orphan-proposal":
        data["proposals"][0]["section_id"] = "unknown"
    elif kind == "boolean-section-revision":
        data["documents"][0]["sections"][0]["revision"] = True
    elif kind == "false-lock-type":
        data["documents"][0]["sections"][0]["locked"] = "false"
    else:
        data["proposals"][0]["unreviewed_extra"] = "unexpected"
    workspace.path.write_text(json.dumps(data))
    before = workspace.path.read_bytes()
    with pytest.raises(ValueError):
        workspace.decide(proposal["id"], 1, "approve", "reviewer")
    assert workspace.path.read_bytes() == before


def retry(workspace, text):
    for attempt in range(100):
        try:
            return workspace.propose(
                "doc-101", "overview", text, "Independent concurrent proposal"
            )
        except Conflict as error:
            if "busy" not in str(error):
                raise
            time.sleep(0.005)
    raise AssertionError("workspace did not become available")


def test_independent_instances_and_processes_preserve_every_concurrent_proposal(
    workspace,
):
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda index: retry(
                    Workspace(workspace.path), f"Thread proposal {index}"
                ),
                range(20),
            )
        )
    assert len({proposal["id"] for proposal in results}) == 20
    program = """
from pathlib import Path
import sys,time
from document_review.store import Workspace,Conflict
workspace=Workspace(Path(sys.argv[1]))
for index in range(5):
 for attempt in range(100):
  try:
   workspace.propose('doc-101','overview',f'Process {sys.argv[2]} proposal {index}','Independent process proposal');break
  except Conflict as error:
   if 'busy' not in str(error):raise
   time.sleep(0.005)
 else:raise AssertionError('workspace remained busy')
"""
    children = [
        subprocess.Popen(
            [sys.executable, "-c", program, str(workspace.path), str(index)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for index in range(3)
    ]
    try:
        for child in children:
            out, err = child.communicate(timeout=10)
            assert child.returncode == 0, err
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.communicate()
    state = workspace.document("doc-101")
    assert (
        len(state["proposals"]) == 35
        and len({proposal["id"] for proposal in state["proposals"]}) == 35
    )
    assert state["document"]["revision"] == 1
    assert workspace.path.stat().st_mode & 0o777 == 0o600
    assert Path(str(workspace.path) + ".lock").stat().st_mode & 0o777 == 0o600
    assert list(workspace.path.parent.glob("*.tmp")) == []


def test_failed_atomic_replace_leaves_original_state_and_removes_only_owned_temp(
    workspace, monkeypatch
):
    import document_review.store as module

    before = workspace.path.read_bytes()
    unrelated = workspace.path.parent / "unrelated.tmp"
    unrelated.write_text("Other owner")

    def fail(source, destination):
        assert Path(source).stat().st_mode & 0o777 == 0o600
        raise OSError("Synthetic publication failure")

    monkeypatch.setattr(module.os, "replace", fail)
    with pytest.raises(OSError, match="publication"):
        workspace.propose(
            "doc-101",
            "overview",
            "A replacement that must not publish.",
            "Atomic failure probe",
        )
    assert (
        workspace.path.read_bytes() == before and unrelated.read_text() == "Other owner"
    )
    assert list(workspace.path.parent.glob(".workspace.json.*.tmp")) == []


def test_loaded_or_new_oversized_state_and_text_are_rejected(workspace):
    before = workspace.path.read_bytes()
    with pytest.raises(ValueError):
        workspace.propose("doc-101", "overview", "x" * 20001, "Oversize text")
    assert workspace.path.read_bytes() == before
    workspace.path.write_bytes(b" " * (4 * 1024 * 1024 + 1))
    with pytest.raises(ValueError, match="4 MiB"):
        Workspace(workspace.path)
