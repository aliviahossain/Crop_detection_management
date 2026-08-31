from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# Isolate tests from the developer's real database and uploads. Must be set
# before app.config is imported anywhere.
TEST_DIR = BACKEND / ".pytest-tmp"
TEST_DIR.mkdir(exist_ok=True)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{(TEST_DIR / 'test.db').as_posix()}")
os.environ.setdefault("UPLOAD_DIR", str(TEST_DIR / "uploads"))
os.environ.setdefault("OPENWEATHER_API_KEY", "")
os.environ.setdefault("ANTHROPIC_API_KEY", "")
os.environ.setdefault("ADVISORY_BACKEND", "lexical")
# Pin the language set so the suite does not depend on a developer .env.
os.environ.setdefault("SUPPORTED_LANGUAGES", "en,mr,hi,bn")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _fresh_schema():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def sample_image(tmp_path) -> Path:
    from PIL import Image

    path = tmp_path / "leaf.jpg"
    Image.new("RGB", (320, 240), (60, 120, 60)).save(path)
    return path
