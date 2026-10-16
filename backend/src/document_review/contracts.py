"""Strict bounded synthetic document and proposal state."""

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

    @model_validator(mode="after")
    def valid(self):
        for value in (self.id, self.document_id, self.section_id):
            identifier(value)
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


class WorkspaceData(StrictModel):
    documents: list[Document] = Field(min_length=1, max_length=100)
    proposals: list[Proposal] = Field(max_length=1000)

    @model_validator(mode="after")
    def valid(self):
        documents = {document.id: document for document in self.documents}
        if len(documents) != len(self.documents):
            raise ValueError("duplicate document ID")
        if len({proposal.id for proposal in self.proposals}) != len(self.proposals):
            raise ValueError("duplicate proposal ID")
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
        return self


class Decision(StrictModel):
    revision: int = Field(ge=1, le=SAFE_INTEGER)
    decision: Literal["approve", "reject"]
    actor: str = Field(min_length=1, max_length=100)

    @field_validator("actor")
    @classmethod
    def named_actor(cls, value):
        return identifier(value, "decision actor")
