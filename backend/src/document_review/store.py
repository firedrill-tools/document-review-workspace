"""Committed document sections and proposals shared by UI and copilot tools."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from threading import Lock


class Conflict(Exception):
    pass


class Workspace:
    def __init__(self, path: Path):
        if not path.exists():
            raise FileNotFoundError(f"workspace missing: {path}")
        self.path = path
        self.lock = Lock()

    def _read(self) -> dict:
        return json.loads(self.path.read_text())

    def _write(self, data: dict) -> None:
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, indent=2) + "\n")
        os.replace(temporary, self.path)

    @staticmethod
    def _document(data: dict, document_id: str) -> dict:
        document = next((item for item in data["documents"] if item["id"] == document_id), None)
        if document is None:
            raise KeyError("unknown document")
        return document

    @staticmethod
    def _section(document: dict, section_id: str) -> dict:
        section = next((item for item in document["sections"] if item["id"] == section_id), None)
        if section is None:
            raise KeyError("unknown section")
        return section

    def documents(self) -> list[dict]:
        return [{"id": item["id"], "title": item["title"], "revision": item["revision"]}
                for item in self._read()["documents"]]

    def document(self, document_id: str) -> dict:
        data = self._read()
        document = self._document(data, document_id)
        return {"document": document,
                "proposals": [item for item in data["proposals"] if item["document_id"] == document_id]}

    def propose(self, document_id: str, section_id: str, replacement_text: str, reason: str) -> dict:
        if not replacement_text.strip() or not reason.strip():
            raise ValueError("replacement text and reason are required")
        with self.lock:
            data = self._read()
            document = self._document(data, document_id)
            section = self._section(document, section_id)
            if section["locked"]:
                raise Conflict("section is protected from edits")
            if replacement_text.strip() == section["text"]:
                raise ValueError("replacement must differ from current text")
            proposal = {
                "id": str(uuid.uuid4()), "document_id": document_id, "section_id": section_id,
                "original_text": section["text"], "replacement_text": replacement_text.strip(),
                "reason": reason.strip(), "base_section_revision": section["revision"],
                "revision": 1, "status": "pending", "decision_actor": None,
            }
            data["proposals"].append(proposal)
            self._write(data)
            return proposal

    def decide(self, proposal_id: str, revision: int, decision: str, actor: str) -> dict:
        if decision not in {"approve", "reject"}:
            raise ValueError("decision must be approve or reject")
        if not actor.strip():
            raise ValueError("decision actor is required")
        with self.lock:
            data = self._read()
            proposal = next((item for item in data["proposals"] if item["id"] == proposal_id), None)
            if proposal is None:
                raise KeyError("unknown proposal")
            if proposal["revision"] != revision or proposal["status"] != "pending":
                raise Conflict("proposal changed; reload before deciding")
            document = self._document(data, proposal["document_id"])
            section = self._section(document, proposal["section_id"])
            if decision == "approve":
                if section["locked"]:
                    raise Conflict("section is protected from edits")
                if section["revision"] != proposal["base_section_revision"] or (
                    section["text"] != proposal["original_text"]):
                    raise Conflict("section changed since proposal; review the latest text")
                section["text"] = proposal["replacement_text"]
                section["revision"] += 1
                document["revision"] += 1
                proposal["status"] = "approved"
            else:
                proposal["status"] = "rejected"
            proposal["revision"] += 1
            proposal["decision_actor"] = actor.strip()
            self._write(data)
            return {"proposal": proposal, "document": document}
