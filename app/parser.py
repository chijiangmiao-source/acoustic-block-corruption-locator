"""Parser for ACLG acoustic-inspection binary records.

Record layout (little-endian):

    header:  4 bytes  ASCII magic "ACLG"
             1 byte   uint8 version, must be 1
             2 bytes  uint16 declared block count
    block:   2 bytes  uint16 sample count N
             2*N bytes  N signed 16-bit samples

The parser stops at the first structural error and raises RecordError;
a fully valid record yields a RecordSummary.

With include_block_stats=True the same single pass also tallies each
block's sample count and min/max sample values (None for empty blocks).
Stats are only ever returned for a fully valid record: any structural
error aborts the pass with RecordError, so partial stats never escape.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import StrEnum

MAGIC = b"ACLG"
VERSION = 1
HEADER_SIZE = 7  # 4 magic + 1 version + 2 block count
BLOCK_LEN_SIZE = 2
SAMPLE_SIZE = 2


class ErrorCode(StrEnum):
    HEADER_INVALID = "HEADER_INVALID"
    TRUNCATED_BLOCK = "TRUNCATED_BLOCK"
    TRAILING_BYTES = "TRAILING_BYTES"


class RecordError(Exception):
    """First structural error found in a record."""

    def __init__(self, code: ErrorCode, message: str, block_index: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.block_index = block_index


@dataclass(frozen=True, slots=True)
class BlockStats:
    """Sample summary for one block, in record order."""

    index: int
    sample_count: int
    min: int | None  # None when the block holds no samples
    max: int | None


@dataclass(frozen=True, slots=True)
class RecordSummary:
    block_count: int
    total_samples: int
    # Populated only when the caller asked for per-block stats.
    block_stats: tuple[BlockStats, ...] | None = None


def parse_record(data: bytes, *, include_block_stats: bool = False) -> RecordSummary:
    """Validate one ACLG record and return its summary.

    Raises RecordError with the first problem encountered.
    """
    if len(data) < HEADER_SIZE:
        raise RecordError(
            ErrorCode.HEADER_INVALID,
            f"incomplete header: got {len(data)} of {HEADER_SIZE} required bytes",
        )
    if data[:4] != MAGIC:
        raise RecordError(
            ErrorCode.HEADER_INVALID,
            f"bad magic {data[:4]!r}: expected {MAGIC!r}",
        )
    version = data[4]
    if version != VERSION:
        raise RecordError(
            ErrorCode.HEADER_INVALID,
            f"unsupported version {version}: expected {VERSION}",
        )

    (block_count,) = struct.unpack_from("<H", data, 5)
    offset = HEADER_SIZE
    total_samples = 0
    stats: list[BlockStats] = []

    for index in range(block_count):
        if len(data) - offset < BLOCK_LEN_SIZE:
            raise RecordError(
                ErrorCode.TRUNCATED_BLOCK,
                f"block {index}: missing 2-byte sample count",
                block_index=index,
            )
        (sample_count,) = struct.unpack_from("<H", data, offset)
        offset += BLOCK_LEN_SIZE

        needed = sample_count * SAMPLE_SIZE
        remaining = len(data) - offset
        if remaining < needed:
            raise RecordError(
                ErrorCode.TRUNCATED_BLOCK,
                f"block {index}: declared {sample_count} samples ({needed} bytes) "
                f"but only {remaining} bytes remain",
                block_index=index,
            )
        if include_block_stats:
            samples = struct.unpack_from(f"<{sample_count}h", data, offset)
            stats.append(
                BlockStats(
                    index=index,
                    sample_count=sample_count,
                    min=min(samples, default=None),
                    max=max(samples, default=None),
                )
            )
        offset += needed
        total_samples += sample_count

    trailing = len(data) - offset
    if trailing:
        raise RecordError(
            ErrorCode.TRAILING_BYTES,
            f"{trailing} unexpected byte(s) after {block_count} declared block(s)",
        )

    return RecordSummary(
        block_count=block_count,
        total_samples=total_samples,
        block_stats=tuple(stats) if include_block_stats else None,
    )
