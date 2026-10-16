"""Hash-bound synthetic document cases and exclusive private copies."""

import hashlib
import json
import os
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from .contracts import MAX_STATE_BYTES, StrictModel, WorkspaceData, identifier


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def data_root():
    bundled = Path(__file__).parent / "sample_data"
    return bundled if bundled.is_dir() else Path(__file__).parents[2] / "data"


def read_bounded(path):
    with Path(path).open("rb") as file:
        raw = file.read(MAX_STATE_BYTES + 1)
    if len(raw) > MAX_STATE_BYTES:
        raise ValueError("dataset file exceeds 4 MiB")
    return raw


class Case(StrictModel):
    id: str
    profile: Literal["starter", "busy", "ambiguous", "boundary"]
    file: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_id: str
    section_id: str
    task: str = Field(min_length=1, max_length=2000)
    focus: str = Field(min_length=1, max_length=3000)
    documents: int = Field(ge=1, le=100)
    sections: int = Field(ge=1, le=10000)
    proposals: int = Field(ge=0, le=1000)
    approved: int = Field(ge=0, le=1000)
    rejected: int = Field(ge=0, le=1000)
    pending: int = Field(ge=0, le=1000)

    @model_validator(mode="after")
    def valid(self):
        for value in (self.id, self.document_id, self.section_id):
            identifier(value)
        if not self.task.strip() or not self.focus.strip():
            raise ValueError("blank scenario metadata")
        if self.proposals != self.approved + self.rejected + self.pending:
            raise ValueError("proposal counts do not agree")
        return self


class Manifest(StrictModel):
    id: Literal["synthetic-document-review"]
    version: int = Field(ge=1, le=1)
    synthetic: bool
    cases: list[Case] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def valid(self):
        if self.synthetic is not True:
            raise ValueError("dataset must be synthetic")
        if len({case.id for case in self.cases}) != len(self.cases) or len(
            {case.file for case in self.cases}
        ) != len(self.cases):
            raise ValueError("duplicate case identity/path")
        return self


def load_manifest(root=None):
    root = Path(root) if root is not None else data_root()
    manifest_raw = read_bounded(root / "manifest.json")
    manifest = Manifest.model_validate_json(manifest_raw)
    fixtures = {}
    for case in manifest.cases:
        file = Path(case.file)
        if (
            not case.file
            or file.is_absolute()
            or ".." in file.parts
            or "\\" in case.file
        ):
            raise ValueError("case path must be a confined relative path")
        source = (root / file).resolve(strict=True)
        if not source.is_relative_to(root.resolve(strict=True)):
            raise ValueError("case path escapes dataset root")
        raw = read_bounded(source)
        if sha(raw) != case.sha256:
            raise ValueError("case hash differs from manifest")
        state = WorkspaceData.model_validate_json(raw)
        identity = {
            "id": manifest.id,
            "version": manifest.version,
            "profile": case.profile,
            "case_id": case.id,
        }
        if (
            state.synthetic is not True
            or state.dataset is None
            or state.dataset.model_dump() != identity
        ):
            raise ValueError("case identity differs from manifest")
        document = next(
            (doc for doc in state.documents if doc.id == case.document_id), None
        )
        if document is None or not any(
            part.id == case.section_id for part in document.sections
        ):
            raise ValueError("selected document/section does not exist")
        actual = {
            "documents": len(state.documents),
            "sections": sum(len(doc.sections) for doc in state.documents),
            "proposals": len(state.proposals),
            **{
                status: sum(proposal.status == status for proposal in state.proposals)
                for status in ("approved", "rejected", "pending")
            },
        }
        if any(getattr(case, name) != count for name, count in actual.items()):
            raise ValueError("case populations differ from manifest")
        if any(
            proposal.origin != "human_import"
            or proposal.created_by_run is not None
            or proposal.created_by_thread is not None
            for proposal in state.proposals
        ):
            raise ValueError(
                "fixture prior decisions must be human imports, never model executions"
            )
        if any(
            proposal.created_at is None
            or proposal.status != "pending"
            and proposal.decided_at is None
            for proposal in state.proposals
        ):
            raise ValueError(
                "imported history needs explicit creation/decision timestamps"
            )
        fixtures[case.id] = raw
    return manifest, sha(manifest_raw), fixtures


def list_cases(root=None):
    manifest, digest, _ = load_manifest(root)
    return {**manifest.model_dump(mode="json"), "manifest_sha256": digest}


def select_case(case_id, root=None):
    identifier(case_id, "case ID")
    manifest, digest, fixtures = load_manifest(root)
    case = next((case for case in manifest.cases if case.id == case_id), None)
    if case is None:
        raise ValueError("unknown document review case")
    return case, fixtures[case.id], digest


def initialize_case(case_id, target, root=None):
    case, raw, manifest_digest = select_case(case_id, root)
    # Keep the final component unresolved so an existing symlink is refused by O_EXCL.
    target = Path(target).absolute()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(raw)
            file.flush()
            os.fsync(file.fileno())
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    state = json.loads(raw)
    return {
        "workspace_path": str(target),
        "dataset": state["dataset"],
        "fixture_sha256": case.sha256,
        "manifest_sha256": manifest_digest,
        "document_id": case.document_id,
        "section_id": case.section_id,
        "task": case.task,
    }
