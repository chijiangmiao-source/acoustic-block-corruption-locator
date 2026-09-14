"""Pydantic response models for the inspection API."""

from typing import Literal

from pydantic import BaseModel, Field, SerializerFunctionWrapHandler, model_serializer

from .parser import ErrorCode


class BlockStatsBody(BaseModel):
    """Per-block sample summary, emitted in record order."""

    index: int = Field(ge=0, description="Zero-based position of the block in the record")
    sample_count: int = Field(ge=0, description="Number of samples in this block")
    min: int | None = Field(description="Smallest sample value; null for empty blocks")
    max: int | None = Field(description="Largest sample value; null for empty blocks")


class PassResponse(BaseModel):
    """Returned when the record parses cleanly end to end."""

    status: Literal["PASS"] = "PASS"
    block_count: int = Field(ge=0, description="Declared block count from the header")
    total_samples: int = Field(ge=0, description="Sum of samples across all blocks")
    block_stats: list[BlockStatsBody] | None = Field(
        default=None,
        description="Per-block sample stats; present only when include_block_stats=true",
    )

    @model_serializer(mode="wrap")
    def _omit_block_stats_unless_requested(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, object]:
        # Drop only the top-level key when stats were not requested; explicit
        # nulls inside block_stats (empty blocks) must survive serialization.
        data = handler(self)
        if self.block_stats is None:
            data.pop("block_stats", None)
        return data


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
