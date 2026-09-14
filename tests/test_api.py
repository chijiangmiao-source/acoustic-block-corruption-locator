"""API contract tests via FastAPI TestClient."""

import struct

from fastapi.testclient import TestClient

from app.main import MAX_UPLOAD_BYTES, app

client = TestClient(app)


def make_record(sample_counts: list[int], trailing: bytes = b"") -> bytes:
    body = b"".join(struct.pack("<H", n) + bytes(2 * n) for n in sample_counts)
    return b"ACLG" + bytes([1]) + struct.pack("<H", len(sample_counts)) + body + trailing


def post(payload: bytes):
    return client.post(
        "/inspect",
        files={"file": ("record.aclg", payload, "application/octet-stream")},
    )


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_valid_record_passes():
    resp = post(make_record([3, 0, 4]))
    assert resp.status_code == 200
    assert resp.json() == {"status": "PASS", "block_count": 3, "total_samples": 7}


def test_valid_empty_record_passes():
    resp = post(make_record([]))
    assert resp.status_code == 200
    assert resp.json() == {"status": "PASS", "block_count": 0, "total_samples": 0}


def test_header_invalid():
    resp = post(b"XX")
    assert resp.status_code == 422
    body = resp.json()
    assert body["status"] == "FAIL"
    assert body["error"]["code"] == "HEADER_INVALID"
    assert body["error"]["block_index"] is None


def test_truncated_block_carries_zero_based_index():
    # Header declares 2 blocks; block 0 is complete, then one dangling byte.
    record = b"ACLG" + bytes([1]) + struct.pack("<H", 2) + make_record([2])[7:] + b"\x01"
    resp = post(record)
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "TRUNCATED_BLOCK"
    assert body["error"]["block_index"] == 1


def test_trailing_bytes():
    resp = post(make_record([1], trailing=b"\x00"))
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "TRAILING_BYTES"


def test_exactly_max_size_is_accepted_for_parsing():
    # Largest valid record is 8 MiB - 1 (block bytes are always even, header is 7).
    counts = [65535] * 63 + [65531]
    record = make_record(counts)
    assert len(record) == MAX_UPLOAD_BYTES - 1
    resp = post(record)
    assert resp.status_code == 200
    assert resp.json() == {
        "status": "PASS",
        "block_count": 64,
        "total_samples": sum(counts),
    }

    # Exactly 8 MiB: still processed (here: one trailing byte -> TRAILING_BYTES).
    resp = post(record + b"\x00")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "TRAILING_BYTES"


def test_over_max_size_returns_413():
    payload = make_record([]) + bytes(MAX_UPLOAD_BYTES + 1 - 7)
    assert len(payload) == MAX_UPLOAD_BYTES + 1
    resp = post(payload)
    assert resp.status_code == 413


def test_missing_file_field_rejected():
    resp = client.post("/inspect", files={"wrong": ("a.bin", b"ACLG")})
    assert resp.status_code == 422
