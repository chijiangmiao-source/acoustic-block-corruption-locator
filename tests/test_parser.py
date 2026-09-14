"""Unit tests for the ACLG record parser."""

import struct

import pytest

from app.parser import BlockStats, ErrorCode, RecordError, parse_record


def make_record(
    sample_counts: list[int],
    *,
    magic: bytes = b"ACLG",
    version: int = 1,
    declared_blocks: int | None = None,
    trailing: bytes = b"",
) -> bytes:
    body = b"".join(struct.pack("<H", n) + bytes(2 * n) for n in sample_counts)
    if declared_blocks is None:
        declared_blocks = len(sample_counts)
    return magic + bytes([version]) + struct.pack("<H", declared_blocks) + body + trailing


def make_record_with_samples(blocks: list[list[int]]) -> bytes:
    body = b"".join(
        struct.pack("<H", len(samples)) + struct.pack(f"<{len(samples)}h", *samples)
        for samples in blocks
    )
    return b"ACLG" + bytes([1]) + struct.pack("<H", len(blocks)) + body


def test_valid_record_with_multiple_blocks():
    summary = parse_record(make_record([3, 0, 5]))
    assert summary.block_count == 3
    assert summary.total_samples == 8


def test_valid_empty_record():
    summary = parse_record(make_record([]))
    assert summary.block_count == 0
    assert summary.total_samples == 0


def test_sample_values_are_not_inspected():
    # 0xFFFF is a valid int16 (-1); only structure matters.
    record = b"ACLG" + bytes([1]) + struct.pack("<H", 1) + struct.pack("<H", 2) + b"\xff" * 4
    summary = parse_record(record)
    assert summary.total_samples == 2


@pytest.mark.parametrize("size", range(7))
def test_incomplete_header(size):
    record = make_record([1])[:size]
    with pytest.raises(RecordError) as excinfo:
        parse_record(record)
    assert excinfo.value.code == ErrorCode.HEADER_INVALID
    assert excinfo.value.block_index is None


def test_bad_magic():
    with pytest.raises(RecordError) as excinfo:
        parse_record(make_record([1], magic=b"XXXX"))
    assert excinfo.value.code == ErrorCode.HEADER_INVALID


@pytest.mark.parametrize("version", [0, 2, 255])
def test_bad_version(version):
    with pytest.raises(RecordError) as excinfo:
        parse_record(make_record([1], version=version))
    assert excinfo.value.code == ErrorCode.HEADER_INVALID


def test_missing_sample_count_field():
    # Two blocks declared; block 0 complete, then a single dangling byte.
    record = make_record([4], declared_blocks=2, trailing=b"\x00")
    with pytest.raises(RecordError) as excinfo:
        parse_record(record)
    assert excinfo.value.code == ErrorCode.TRUNCATED_BLOCK
    assert excinfo.value.block_index == 1


def test_missing_sample_count_at_record_end():
    record = make_record([], declared_blocks=1)
    with pytest.raises(RecordError) as excinfo:
        parse_record(record)
    assert excinfo.value.code == ErrorCode.TRUNCATED_BLOCK
    assert excinfo.value.block_index == 0


def test_truncated_sample_data():
    # Block declares 4 samples but only 3 samples' worth of bytes follow.
    record = b"ACLG" + bytes([1]) + struct.pack("<H", 1) + struct.pack("<H", 4) + bytes(6)
    with pytest.raises(RecordError) as excinfo:
        parse_record(record)
    assert excinfo.value.code == ErrorCode.TRUNCATED_BLOCK
    assert excinfo.value.block_index == 0


def test_truncated_sample_data_in_later_block():
    record = make_record([2, 3], declared_blocks=2)[:-4]  # cut into block 1's samples
    with pytest.raises(RecordError) as excinfo:
        parse_record(record)
    assert excinfo.value.code == ErrorCode.TRUNCATED_BLOCK
    assert excinfo.value.block_index == 1


def test_trailing_bytes_after_all_blocks():
    with pytest.raises(RecordError) as excinfo:
        parse_record(make_record([1], trailing=b"\xde\xad"))
    assert excinfo.value.code == ErrorCode.TRAILING_BYTES
    assert excinfo.value.block_index is None


def test_trailing_bytes_with_zero_declared_blocks():
    with pytest.raises(RecordError) as excinfo:
        parse_record(make_record([], trailing=b"\x00"))
    assert excinfo.value.code == ErrorCode.TRAILING_BYTES


def test_only_first_error_is_reported():
    # Bad magic AND trailing garbage: header error wins.
    with pytest.raises(RecordError) as excinfo:
        parse_record(make_record([1], magic=b"NOPE", trailing=b"junk"))
    assert excinfo.value.code == ErrorCode.HEADER_INVALID

    # Truncated block AND would-be trailing bytes: truncation wins.
    record = make_record([1], declared_blocks=3, trailing=b"\xff" * 9)
    with pytest.raises(RecordError) as excinfo:
        parse_record(record)
    assert excinfo.value.code == ErrorCode.TRUNCATED_BLOCK
    assert excinfo.value.block_index == 1


def test_maximum_declared_values():
    summary = parse_record(make_record([65535]))
    assert summary.block_count == 1
    assert summary.total_samples == 65535


def test_block_stats_not_computed_by_default():
    record = make_record_with_samples([[1, -2], []])
    assert parse_record(record).block_stats is None
    assert parse_record(record, include_block_stats=False).block_stats is None


def test_block_stats_cover_extremes_and_empty_blocks_in_order():
    record = make_record_with_samples([[3, -7, 12], [], [-32768, 0, 32767]])
    summary = parse_record(record, include_block_stats=True)
    assert summary.block_count == 3
    assert summary.total_samples == 6
    assert summary.block_stats == (
        BlockStats(index=0, sample_count=3, min=-7, max=12),
        BlockStats(index=1, sample_count=0, min=None, max=None),
        BlockStats(index=2, sample_count=3, min=-32768, max=32767),
    )


def test_block_stats_empty_record():
    summary = parse_record(make_record([]), include_block_stats=True)
    assert summary.block_stats == ()


def test_block_stats_do_not_change_error_priority():
    # Truncation in block 1 still aborts the pass; no summary (hence no
    # partial stats for the already-tallied block 0) is ever produced.
    record = make_record_with_samples([[5, -5], [1, 2, 3, 4]])[:-6]
    with pytest.raises(RecordError) as excinfo:
        parse_record(record, include_block_stats=True)
    assert excinfo.value.code == ErrorCode.TRUNCATED_BLOCK
    assert excinfo.value.block_index == 1
