from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PROPOSAL_SCHEMA_VERSION = "pr-guard.hermes-proposal/v1"
REQUIRED_PROPOSAL_FIELDS = {"action", "new_content", "message", "rationale"}


class Metadata(BaseModel):
    """Repository/PR metadata forwarded by pr-guard-bot."""

    model_config = ConfigDict(extra="allow")

    repo: str | None = None
    pr_number: int | None = None
    base_ref: str | None = None
    head_ref: str | None = None
    head_sha: str | None = None


class DriftPayload(BaseModel):
    """Minimum drift fields needed by the adapter.

    Extra drift attributes are kept so the Hermes prompt can see the full
    detector context without this adapter needing to track every field.
    """

    model_config = ConfigDict(extra="allow")

    source: str
    quote: str
    source_file: str | None = None
    line: int | None = None
    severity: str | None = None
    score: float | None = None

    @field_validator("source", "quote")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("must be non-empty")
        return value


class ProposalRequest(BaseModel):
    """Validated PR Guard → Hermes adapter request."""

    model_config = ConfigDict(extra="allow")

    schema_version: str | None = None
    task: str
    metadata: Metadata = Field(default_factory=Metadata)
    drift: DriftPayload
    proposal_shape: list[str]
    seed_md_text: str | None = None
    seed_md_path: str = "SEED.md"
    repo_context: str | None = None
    output_path: str | None = None

    @field_validator("task")
    @classmethod
    def _task_non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("task must be non-empty")
        return value

    @model_validator(mode="after")
    def _validate_shape_and_task_fields(self) -> "ProposalRequest":
        shape = set(self.proposal_shape or [])
        if not REQUIRED_PROPOSAL_FIELDS.issubset(shape):
            missing = sorted(REQUIRED_PROPOSAL_FIELDS - shape)
            raise ValueError(f"proposal_shape missing required fields: {missing}")

        if self.task == "seed_fix" and self.seed_md_text is None:
            raise ValueError("seed_fix requires seed_md_text")
        if self.task == "code_fix" and self.repo_context is None:
            raise ValueError("code_fix requires repo_context")
        return self

    def prompt_payload(self) -> dict[str, Any]:
        """Return compact JSON-serializable context for the Hermes user prompt."""

        return self.model_dump(exclude_none=True, mode="json")


class BlockingDriftRequest(BaseModel):
    """Validated request for semantic blocking drift classification."""

    model_config = ConfigDict(extra="allow")

    schema_version: str | None = None
    task: str
    metadata: Metadata = Field(default_factory=Metadata)
    advisory_drifts: list[DriftPayload]
    diff_summary: str = ""
    decision_shape: dict[str, Any] | None = None

    @field_validator("task")
    @classmethod
    def _task_non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("task must be non-empty")
        return value

    @model_validator(mode="after")
    def _validate_task(self) -> "BlockingDriftRequest":
        if self.task != "blocking_drift_classification":
            raise ValueError("BlockingDriftRequest requires blocking_drift_classification task")
        return self

    def prompt_payload(self) -> dict[str, Any]:
        """Return compact JSON-serializable context for the Hermes user prompt."""

        return self.model_dump(exclude_none=True, mode="json")


class ReviewRequest(BaseModel):
    """Validated request for general PR review."""

    model_config = ConfigDict(extra="allow")

    schema_version: str | None = None
    task: str
    metadata: Metadata = Field(default_factory=Metadata)
    diff_summary: str = ""
    repo_context: str = ""
    report_shape: dict[str, Any] | None = None

    @field_validator("task")
    @classmethod
    def _task_non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("task must be non-empty")
        return value

    @model_validator(mode="after")
    def _validate_task(self) -> "ReviewRequest":
        if self.task != "review":
            raise ValueError("ReviewRequest requires review task")
        return self

    def prompt_payload(self) -> dict[str, Any]:
        """Return compact JSON-serializable context for the Hermes user prompt."""

        return self.model_dump(exclude_none=True, mode="json")
