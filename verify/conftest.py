import os

import httpx
import pytest


@pytest.fixture(scope="session")
def client() -> httpx.Client:
    base_url = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    with httpx.Client(base_url=base_url, timeout=30.0) as session:
        yield session
