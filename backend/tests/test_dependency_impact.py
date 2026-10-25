import uuid
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db.session import SessionLocal
from app.main import app
from app.models.models import Dependency, Document, Project, User, UserToken
from app.services.security import hash_token


def test_dependency_impact_resolves_python_from_import_statement():
    suffix = uuid.uuid4().hex
    user = User(email=f"dependency-impact-{suffix}@example.test", password_hash="unused")
    token = f"dependency-impact-token-{suffix}"
    db = SessionLocal()
    try:
        db.add(user)
        db.flush()
        project = Project(owner_id=user.id, name=f"dependency-impact-{suffix}")
        db.add(project)
        db.flush()
        helper = Document(
            project_id=project.id, path="helpers.py", language="python",
            content_hash="a" * 64, content="def work():\n    return 1\n",
        )
        caller = Document(
            project_id=project.id, path="api.py", language="python",
            content_hash="b" * 64, content="from helpers import work\ndef call():\n    return work()\n",
        )
        js_helper = Document(
            project_id=project.id, path="js/helpers.js", language="javascript",
            content_hash="c" * 64, content="export const work = () => 1;\n",
        )
        js_caller = Document(
            project_id=project.id, path="js/api.js", language="javascript",
            content_hash="d" * 64, content="import { work } from './helpers.js';\nexport const call = () => work();\n",
        )
        db.add_all([helper, caller, js_helper, js_caller])
        db.flush()
        db.add_all([
            Dependency(project_id=project.id, source_document_id=caller.id, source_symbol="call", target="from helpers import work", relation_type="import"),
            Dependency(project_id=project.id, source_document_id=js_caller.id, source_symbol="call", target="import { work } from './helpers.js'", relation_type="import"),
            UserToken(user_id=user.id, token_hash=hash_token(token), expires_at=datetime.utcnow() + timedelta(days=1)),
        ])
        db.commit()
        project_id, user_id = project.id, user.id

        with TestClient(app) as client:
            response = client.get(
                f"/api/projects/{project_id}/impact",
                params={"path": "helpers.py"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert response.status_code == 200
        assert response.json()["impacted_files"] == [{"path": "api.py", "depth": 1}]
        js_response = client.get(
            f"/api/projects/{project_id}/impact",
            params={"path": "js/helpers.js"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert js_response.status_code == 200
        assert js_response.json()["impacted_files"] == [{"path": "js/api.js", "depth": 1}]
    finally:
        db.rollback()
        if "project_id" in locals():
            db.execute(delete(Project).where(Project.id == project_id))
        if "user_id" in locals():
            db.execute(delete(UserToken).where(UserToken.user_id == user_id))
            db.execute(delete(User).where(User.id == user_id))
        db.commit()
        db.close()
