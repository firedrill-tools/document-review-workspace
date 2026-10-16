"""Committed document sections and proposals shared by UI and copilot tools."""

from __future__ import annotations

from datetime import datetime, timezone
from contextlib import contextmanager
import fcntl
import json
import hashlib
import os
import uuid
import time
from tempfile import NamedTemporaryFile
from pathlib import Path
from threading import Lock

from .contracts import (
    MAX_STATE_BYTES,
    SAFE_INTEGER,
    WorkspaceData,
    bounded,
    identifier,
    revision as valid_revision,
)


class Conflict(Exception):
    pass


class Workspace:
    def __init__(self, path: Path):
        if not path.exists():
            raise FileNotFoundError(f"workspace missing: {path}")
        self.path = Path(path).resolve()
        self.lock = Lock()
        self._read()

    def snapshot(self):
        with self.path.open("rb") as source:
            raw = source.read(MAX_STATE_BYTES + 1)
        if len(raw) > MAX_STATE_BYTES:
            raise ValueError("workspace exceeds 4 MiB")
        data = json.loads(raw)
        WorkspaceData.model_validate(data)
        return {"file_sha256": hashlib.sha256(raw).hexdigest(), "state": data}

    def _read(self) -> dict:
        return self.snapshot()["state"]

    @contextmanager
    def _locked(self):
        # Separate Workspace instances/processes coordinate through the same sidecar.
        # Never remove the lock path: unlinking would allow a second lock inode.
        if not self.lock.acquire(timeout=0.1):
            raise Conflict("workspace is busy; reload current state before retrying")
        descriptor = None
        acquired = False
        try:
            flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(str(self.path) + ".lock", flags, 0o600)
            deadline = time.monotonic() + 0.1
            while not acquired:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise Conflict(
                            "workspace is busy; reload current state before retrying"
                        )
                    time.sleep(0.005)
            yield
        finally:
            if descriptor is not None:
                if acquired:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)
            self.lock.release()

    def _write(self, data: dict, commit_guard=None) -> None:
        if commit_guard:
            commit_guard()
        WorkspaceData.model_validate(data)
        raw = (json.dumps(data, indent=2) + "\n").encode("utf-8")
        if len(raw) > MAX_STATE_BYTES:
            raise ValueError("workspace exceeds 4 MiB")
        temporary = None
        try:
            with NamedTemporaryFile(
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            if commit_guard:
                commit_guard()
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    @staticmethod
    def _document(data: dict, document_id: str) -> dict:
        document = next(
            (item for item in data["documents"] if item["id"] == document_id), None
        )
        if document is None:
            raise KeyError("unknown document")
        return document

    @staticmethod
    def _section(document: dict, section_id: str) -> dict:
        section = next(
            (item for item in document["sections"] if item["id"] == section_id), None
        )
        if section is None:
            raise KeyError("unknown section")
        return section

    def documents(self) -> list[dict]:
        return [
            {"id": item["id"], "title": item["title"], "revision": item["revision"]}
            for item in self._read()["documents"]
        ]

    def document(self, document_id: str) -> dict:
        data = self._read()
        document = self._document(data, document_id)
        return {
            "document": document,
            "proposals": [
                item for item in data["proposals"] if item["document_id"] == document_id
            ],
        }

    def propose(
        self,
        document_id: str,
        section_id: str,
        replacement_text: str,
        reason: str,
        *,
        expected_section=None,
        run_id=None,
        thread_id=None,
        commit_guard=None,
    ) -> dict:
        if run_id is not None:
            identifier(run_id, "run ID")
            identifier(thread_id, "thread ID")
            if expected_section is None or commit_guard is None:
                raise ValueError(
                    "model proposal requires an owned source read and commit guard"
                )
        if commit_guard:
            commit_guard()
        identifier(document_id, "document ID")
        identifier(section_id, "section ID")
        bounded(replacement_text, "replacement text", 20000)
        bounded(reason, "reason", 2000)
        with self._locked():
            data = self._read()
            document = self._document(data, document_id)
            section = self._section(document, section_id)
            if (
                expected_section is not None
                and {key: section[key] for key in ("text", "revision", "locked")}
                != expected_section
            ):
                raise Conflict(
                    "section changed since this run read it; read the current source again"
                )
            if section["locked"]:
                raise Conflict("section is protected from edits")
            if replacement_text.strip() == section["text"]:
                raise ValueError("replacement must differ from current text")
            for existing in data["proposals"]:
                if existing["status"] == "pending" and all(
                    existing[key] == value
                    for key, value in {
                        "document_id": document_id,
                        "section_id": section_id,
                        "original_text": section["text"],
                        "base_section_revision": section["revision"],
                        "replacement_text": replacement_text.strip(),
                        "reason": reason.strip(),
                    }.items()
                ):
                    if commit_guard:
                        commit_guard()
                    return {**existing, "proposal_replayed": True}
            proposal = {
                "id": str(uuid.uuid4()),
                "document_id": document_id,
                "section_id": section_id,
                "original_text": section["text"],
                "replacement_text": replacement_text.strip(),
                "reason": reason.strip(),
                "base_section_revision": section["revision"],
                "revision": 1,
                "status": "pending",
                "decision_actor": None,
                "origin": "model_proposal" if run_id else "human_import",
                "created_by_run": run_id,
                "created_by_thread": thread_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "decided_at": None,
            }
            data["proposals"].append(proposal)
            self._write(data, commit_guard)
            return {**proposal, "proposal_replayed": False}

    def decide(
        self, proposal_id: str, revision: int, decision: str, actor: str
    ) -> dict:
        identifier(proposal_id, "proposal ID")
        valid_revision(revision)
        if decision not in {"approve", "reject"}:
            raise ValueError("decision must be approve or reject")
        identifier(actor, "decision actor")
        with self._locked():
            data = self._read()
            proposal = next(
                (item for item in data["proposals"] if item["id"] == proposal_id), None
            )
            if proposal is None:
                raise KeyError("unknown proposal")
            if proposal["revision"] != revision or proposal["status"] != "pending":
                raise Conflict("proposal changed; reload before deciding")
            document = self._document(data, proposal["document_id"])
            section = self._section(document, proposal["section_id"])
            if decision == "approve":
                if (
                    document["revision"] >= SAFE_INTEGER
                    or section["revision"] >= SAFE_INTEGER
                ):
                    raise Conflict(
                        "revision limit reached; this document cannot accept another edit"
                    )
                if section["locked"]:
                    raise Conflict("section is protected from edits")
                if section["revision"] != proposal["base_section_revision"] or (
                    section["text"] != proposal["original_text"]
                ):
                    raise Conflict(
                        "section changed since proposal; review the latest text"
                    )
                section["text"] = proposal["replacement_text"]
                section["revision"] += 1
                document["revision"] += 1
                proposal["status"] = "approved"
            else:
                proposal["status"] = "rejected"
            proposal["revision"] += 1
            proposal["decision_actor"] = actor.strip()
            proposal["decided_at"] = datetime.now(timezone.utc).isoformat()
            self._write(data)
            return {"proposal": proposal, "document": document}
