import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from document_review.api import create_app
from document_review.store import Conflict, Workspace


@pytest.fixture
def workspace(tmp_path):
    source = Path(__file__).parents[2] / "fixtures" / "starter.json"
    target = tmp_path / "workspace.json"
    shutil.copyfile(source, target)
    return Workspace(target)


def test_proposal_does_not_change_document_and_approval_changes_only_one_section(
    workspace,
):
    before = workspace.document("doc-101")["document"]
    original_sections = {item["id"]: item["text"] for item in before["sections"]}
    proposal = workspace.propose(
        "doc-101",
        "acknowledgement",
        "A Sev 2 incident should be acknowledged within 30 minutes.",
        "Bring target into line with current handbook",
    )
    assert workspace.document("doc-101")["document"] == before
    decided = workspace.decide(proposal["id"], proposal["revision"], "approve", "Avery")
    assert decided["proposal"]["status"] == "approved"
    after = workspace.document("doc-101")["document"]
    assert after["revision"] == 2
    assert (
        next(item for item in after["sections"] if item["id"] == "acknowledgement")[
            "revision"
        ]
        == 2
    )
    assert (
        "30 minutes"
        in next(item for item in after["sections"] if item["id"] == "acknowledgement")[
            "text"
        ]
    )
    for section in after["sections"]:
        if section["id"] != "acknowledgement":
            assert section["text"] == original_sections[section["id"]]
            assert section["revision"] == 1
    assert workspace.document("doc-102")["document"]["revision"] == 1


def test_rejected_edit_leaves_text_untouched(workspace):
    before = workspace.document("doc-101")["document"]
    proposal = workspace.propose(
        "doc-101", "overview", "Remove all records.", "Test rejection"
    )
    result = workspace.decide(proposal["id"], 1, "reject", "Avery")
    assert result["proposal"]["status"] == "rejected"
    assert workspace.document("doc-101")["document"] == before
    with pytest.raises(Conflict, match="proposal changed"):
        workspace.decide(proposal["id"], 1, "approve", "Avery")


def test_competing_proposal_for_same_section_is_stale(workspace):
    first = workspace.propose(
        "doc-101", "overview", "First revision.", "First suggestion"
    )
    second = workspace.propose(
        "doc-101", "overview", "Second revision.", "Second suggestion"
    )
    workspace.decide(first["id"], 1, "approve", "Avery")
    with pytest.raises(Conflict, match="section changed"):
        workspace.decide(second["id"], 1, "approve", "Avery")
    assert (
        workspace.document("doc-101")["document"]["sections"][0]["text"]
        == "First revision."
    )


def test_unrelated_section_change_does_not_make_proposal_stale(workspace):
    main = workspace.propose(
        "doc-101", "overview", "A concise overview.", "Clarify opening"
    )
    other = workspace.propose(
        "doc-101", "escalation", "A concise escalation.", "Clarify handoff"
    )
    workspace.decide(other["id"], 1, "approve", "Avery")
    assert (
        workspace.decide(main["id"], 1, "approve", "Avery")["proposal"]["status"]
        == "approved"
    )


def test_protected_section_and_invalid_content_are_rejected(workspace):
    with pytest.raises(Conflict, match="protected"):
        workspace.propose("doc-101", "legal", "Delete the legal text.", "No notice")
    with pytest.raises(ValueError, match="replacement text"):
        workspace.propose("doc-101", "overview", "", "Empty edit")
    with pytest.raises(KeyError, match="unknown section"):
        workspace.propose("doc-101", "imaginary", "New text", "Missing section")


def test_http_api_exposes_committed_state_and_conflicts(workspace):
    client = TestClient(create_app(workspace.path, include_agent=False))
    assert len(client.get("/documents").json()) == 2
    assert client.get("/documents/unknown").status_code == 404
    proposal = workspace.propose(
        "doc-101", "overview", "Approved overview.", "Test API"
    )
    decision = client.post(
        f"/proposals/{proposal['id']}/decision",
        json={"revision": 1, "decision": "approve", "actor": "Avery"},
    )
    assert decision.status_code == 200
    assert (
        client.get("/documents/doc-101").json()["document"]["sections"][0]["text"]
        == "Approved overview."
    )
    assert (
        client.post(
            f"/proposals/{proposal['id']}/decision",
            json={"revision": 1, "decision": "approve", "actor": "Avery"},
        ).status_code
        == 409
    )
