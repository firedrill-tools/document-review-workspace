"""Strict bounded synthetic document and proposal state."""

from datetime import datetime, timedelta
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SAFE_INTEGER = 2**53 - 1
MAX_STATE_BYTES = 4 * 1024 * 1024


def identifier(value, name="identifier"):
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not 1 <= len(value) <= 100
    ):
        raise ValueError(
            f"{name} requires 1–100 characters without surrounding whitespace"
        )
    return value


def revision(value):
    if type(value) is not int or not 1 <= value <= SAFE_INTEGER:
        raise ValueError("revision must be a positive strict safe integer")
    return value


def bounded(value, name, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(
            f"{name} must be nonblank text of at most {maximum} characters"
        )
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Section(StrictModel):
    id: str
    heading: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1, max_length=20000)
    revision: int = Field(ge=1, le=SAFE_INTEGER)
    locked: bool

    @model_validator(mode="after")
    def valid(self):
        identifier(self.id)
        bounded(self.heading, "heading", 300)
        bounded(self.text, "section text", 20000)
        return self


class Document(StrictModel):
    id: str
    title: str = Field(min_length=1, max_length=300)
    revision: int = Field(ge=1, le=SAFE_INTEGER)
    sections: list[Section] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def valid(self):
        identifier(self.id)
        bounded(self.title, "title", 300)
        if len({section.id for section in self.sections}) != len(self.sections):
            raise ValueError("duplicate section ID")
        if self.revision < max(section.revision for section in self.sections):
            raise ValueError("document revision precedes its sections")
        return self


class Proposal(StrictModel):
    id: str
    document_id: str
    section_id: str
    original_text: str = Field(min_length=1, max_length=20000)
    replacement_text: str = Field(min_length=1, max_length=20000)
    reason: str = Field(min_length=1, max_length=2000)
    base_section_revision: int = Field(ge=1, le=SAFE_INTEGER)
    revision: int = Field(ge=1, le=2)
    status: Literal["pending", "approved", "rejected"]
    decision_actor: str | None
    origin: Literal["legacy_unknown", "human_import", "model_proposal"] = (
        "legacy_unknown"
    )
    created_by_run: str | None = None
    created_by_thread: str | None = None
    created_at: str | None = Field(default=None, max_length=40)
    decided_at: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def valid(self):
        for value in (self.id, self.document_id, self.section_id):
            identifier(value)
        if self.origin == "model_proposal":
            identifier(self.created_by_run, "creating run ID")
            if self.created_by_thread is not None:
                identifier(self.created_by_thread, "creating thread ID")
        elif self.created_by_run is not None or self.created_by_thread is not None:
            raise ValueError("non-model history cannot claim a model run")
        timestamps = {}
        for name in ("created_at", "decided_at"):
            value = getattr(self, name)
            if value is not None:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if (
                    "T" not in value
                    or parsed.tzinfo is None
                    or parsed.utcoffset() != timedelta(0)
                ):
                    raise ValueError(
                        "proposal timestamps must be explicit UTC ISO datetimes"
                    )
                timestamps[name] = parsed
        if self.status == "pending" and self.decided_at is not None:
            raise ValueError("pending proposal cannot claim a decision timestamp")
        if len(timestamps) == 2 and timestamps["decided_at"] < timestamps["created_at"]:
            raise ValueError("decision precedes proposal creation")
        bounded(self.original_text, "original text", 20000)
        bounded(self.replacement_text, "replacement text", 20000)
        bounded(self.reason, "reason", 2000)
        if self.original_text == self.replacement_text:
            raise ValueError("proposal does not change text")
        if self.status == "pending":
            if self.revision != 1 or self.decision_actor is not None:
                raise ValueError("pending proposal has decision state")
        else:
            if self.revision != 2:
                raise ValueError("decided proposal requires revision 2")
            identifier(self.decision_actor, "decision actor")
        return self


class DatasetIdentity(StrictModel):
    id: Literal["synthetic-document-review"]
    version: int = Field(ge=1, le=1)
    profile: Literal["starter", "busy", "ambiguous", "boundary"]
    case_id: str

    @model_validator(mode="after")
    def valid(self):
        identifier(self.case_id, "case ID")
        return self


class WorkspaceData(StrictModel):
    synthetic: bool | None = None
    dataset: DatasetIdentity | None = None
    documents: list[Document] = Field(min_length=1, max_length=100)
    proposals: list[Proposal] = Field(max_length=1000)

    @model_validator(mode="after")
    def valid(self):
        documents = {document.id: document for document in self.documents}
        if len(documents) != len(self.documents):
            raise ValueError("duplicate document ID")
        if len({proposal.id for proposal in self.proposals}) != len(self.proposals):
            raise ValueError("duplicate proposal ID")
        if (
            self.synthetic not in (None, True)
            or self.dataset is not None
            and self.synthetic is not True
        ):
            raise ValueError("declared datasets must explicitly be synthetic")
        approved = set()
        for proposal in self.proposals:
            document = documents.get(proposal.document_id)
            section = (
                next(
                    (
                        section
                        for section in document.sections
                        if section.id == proposal.section_id
                    ),
                    None,
                )
                if document
                else None
            )
            if section is None or proposal.base_section_revision > section.revision:
                raise ValueError(
                    "proposal refers to an unknown or impossible section state"
                )
            if proposal.status == "approved":
                consumed = (
                    proposal.document_id,
                    proposal.section_id,
                    proposal.base_section_revision,
                )
                if (
                    consumed in approved
                    or proposal.base_section_revision >= section.revision
                ):
                    raise ValueError(
                        "approved history has conflicting section revisions"
                    )
                approved.add(consumed)
                if (
                    proposal.base_section_revision + 1 == section.revision
                    and proposal.replacement_text != section.text
                ):
                    raise ValueError(
                        "latest approved history differs from committed text"
                    )
        return self


class Decision(StrictModel):
    revision: int = Field(ge=1, le=SAFE_INTEGER)
    decision: Literal["approve", "reject"]
    actor: str = Field(min_length=1, max_length=100)

    @field_validator("actor")
    @classmethod
    def named_actor(cls, value):
        return identifier(value, "decision actor")
