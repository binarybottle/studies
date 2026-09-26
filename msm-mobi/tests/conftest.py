import os
import tempfile

import pytest

# Point the app at a throwaway database and the fake LLM before app import.
_tmp = tempfile.mkdtemp(prefix="msm-test-")
os.environ["STUDY_DB_PATH"] = os.path.join(_tmp, "study.db")
os.environ["MSM_LLM_PROVIDER"] = "fake"
os.environ["MSM_FAKE_LLM_DELAY_S"] = "0"
os.environ["ADMIN_TOKEN"] = "test-admin-token"
os.environ["PROLIFIC_CC_COMPLETE"] = "CCDONE"
os.environ["PROLIFIC_CC_NO_CONSENT"] = "CCNOPE"
os.environ["PROLIFIC_CC_ATTENTION"] = "CCLOOK"

from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A fresh app with an isolated database per test."""
    from app import config, store

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "study.db")
    monkeypatch.setattr(store, "_store", store.Store(tmp_path / "study.db"))
    main.sessions.clear()
    main.locks.clear()
    with TestClient(main.app, follow_redirects=False) as c:
        yield c
