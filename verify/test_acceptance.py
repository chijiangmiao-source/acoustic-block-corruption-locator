"""Acceptance tests run by the one-shot `verify` compose service.

They exercise the live API over HTTP: valid records pass, broken records
fail with the first structural error, and the 8 MiB upload cap holds.
"""

import struct

MAX_UPLOAD_BYTES = 8 * 1024 * 1024


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


def inspect(client, payload: bytes):
    return client.post(
        "/inspect",
        files={"file": ("record.aclg", payload, "application/octet-stream")},
    )


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_valid_record_passes(client):
    resp = inspect(client, make_record([3, 0, 5]))
    assert resp.status_code == 200
    assert resp.json() == {"status": "PASS", "block_count": 3, "total_samples": 8}


def test_valid_empty_record_passes(client):
    resp = inspect(client, make_record([]))
    assert resp.status_code == 200
    assert resp.json() == {"status": "PASS", "block_count": 0, "total_samples": 0}


def test_bad_magic_rejected(client):
    resp = inspect(client, make_record([1], magic=b"XXXX"))
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "HEADER_INVALID"


def test_bad_version_rejected(client):
    resp = inspect(client, make_record([1], version=2))
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "HEADER_INVALID"


def test_incomplete_header_rejected(client):
    resp = inspect(client, b"ACL")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "HEADER_INVALID"


def test_truncated_block_reports_zero_based_index(client):
    # Block 0 complete; block 1 declares 5 samples but only 2 samples' bytes follow.
    record = make_record([2], declared_blocks=2) + struct.pack("<H", 5) + bytes(4)
    resp = inspect(client, record)
    assert resp.status_code == 422
    body = resp.json()
    assert body["status"] == "FAIL"
    assert body["error"]["code"] == "TRUNCATED_BLOCK"
    assert body["error"]["block_index"] == 1


def test_missing_sample_count_field(client):
    record = make_record([2], declared_blocks=2)  # nothing at all for block 1
    resp = inspect(client, record)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "TRUNCATED_BLOCK"
    assert resp.json()["error"]["block_index"] == 1


def test_trailing_bytes_rejected(client):
    resp = inspect(client, make_record([1], trailing=b"\xde\xad"))
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "TRAILING_BYTES"


def test_only_first_error_is_returned(client):
    # Truncated block followed by extra garbage: TRUNCATED_BLOCK, not TRAILING_BYTES.
    record = make_record([1], declared_blocks=3, trailing=b"\xff" * 9)
    resp = inspect(client, record)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "TRUNCATED_BLOCK"


def test_upload_at_size_limit_is_processed(client):
    counts = [65535] * 63 + [65531]
    record = make_record(counts)
    assert len(record) == MAX_UPLOAD_BYTES - 1
    resp = inspect(client, record)
    assert resp.status_code == 200
    assert resp.json() == {
        "status": "PASS",
        "block_count": 64,
        "total_samples": sum(counts),
    }

    # Exactly 8 MiB still gets parsed (this one has a trailing byte).
    resp = inspect(client, record + b"\x00")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "TRAILING_BYTES"


def test_upload_over_size_limit_returns_413(client):
    payload = make_record([]) + bytes(MAX_UPLOAD_BYTES + 1 - 7)
    assert len(payload) == MAX_UPLOAD_BYTES + 1
    resp = inspect(client, payload)
    assert resp.status_code == 413
