from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile

from app.api import routes


@pytest.mark.parametrize(
    ("celery_state", "expected"),
    [
        ("PENDING", "QUEUED"),
        ("STARTED", "PROCESSING"),
        ("RETRY", "PROCESSING"),
        ("SUCCESS", "COMPLETED"),
        ("FAILURE", "FAILED"),
        ("REVOKED", "FAILED"),
    ],
)
def test_index_task_state_is_ui_compatible(celery_state, expected):
    assert routes.map_index_task_state(celery_state) == expected


def test_upload_is_removed_when_queue_submission_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(routes.settings, "upload_dir", str(tmp_path))
    monkeypatch.setattr(routes.settings, "max_upload_mb", 1)
    monkeypatch.setattr(routes, "owned_project", lambda *_: object())

    def fail_delay(*_args):
        raise RuntimeError("broker details must not reach the response")

    monkeypatch.setattr(routes.index_project, "delay", fail_delay)
    upload = UploadFile(filename="sample.zip", file=BytesIO(b"small archive"))

    project = SimpleNamespace(index_generation=0, repository_url=None)
    db = SimpleNamespace(scalar=lambda _statement: project, commit=lambda: None)
    user = SimpleNamespace(id="user-id")
    with pytest.raises(HTTPException) as error:
        routes.upload("project-id", upload, db, user)

    assert error.value.status_code == 503
    assert "broker details" not in error.value.detail
    assert list(tmp_path.rglob("*.zip")) == []
