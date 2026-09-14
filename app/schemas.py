"""Pydantic response models for the inspection API."""

from typing import Literal

from pydantic import BaseModel, Field

from .parser import ErrorCode


class PassResponse(BaseModel):
    """Returned when the record parses cleanly end to end."""

    status: Literal["PASS"] = "PASS"
    block_count: int = Field(ge=0, description="Declared block count from the header")
    total_samples: int = Field(ge=0, description="Sum of samples across all blocks")


class ErrorBody(BaseModel):
    code: ErrorCode
    message: str
    block_index: int | None = Field(
        default=None,
        description="Zero-based index of the offending block (TRUNCATED_BLOCK only)",
    )


class FailResponse(BaseModel):
    """Returned when the record is structurally invalid; carries the first error only."""

    status: Literal["FAIL"] = "FAIL"
    error: ErrorBody
