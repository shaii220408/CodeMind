import uuid

from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db.session import SessionLocal
from app.main import app
from app.models.models import Project, User, UserToken
from app.services.security import hash_password


def test_api_hides_another_users_project():
    suffix = uuid.uuid4().hex
    user_a = User(email=f"a-{suffix}@example.test", password_hash=hash_password("secure-password-a"))
    user_b = User(email=f"b-{suffix}@example.test", password_hash=hash_password("secure-password-b"))
    project = None
    db = SessionLocal()
    try:
        db.add_all([user_a, user_b])
        db.flush()
        project = Project(owner_id=user_a.id, name="private-project")
        db.add(project)
        db.commit()
        project_id, user_a_id, user_b_id = project.id, user_a.id, user_b.id
        email_a, email_b = user_a.email, user_b.email
        db.close()
        db = None

        with TestClient(app) as client:
            response_a = client.post("/api/auth/login", json={"email": email_a, "password": "secure-password-a"})
            response_b = client.post("/api/auth/login", json={"email": email_b, "password": "secure-password-b"})
            assert response_a.status_code == 200
            assert response_b.status_code == 200
            token_a = response_a.json()["access_token"]
            token_b = response_b.json()["access_token"]

            projects_a = client.get("/api/projects", headers={"Authorization": f"Bearer {token_a}"})
            projects_b = client.get("/api/projects", headers={"Authorization": f"Bearer {token_b}"})
            assert project_id in {item["id"] for item in projects_a.json()}
            assert project_id not in {item["id"] for item in projects_b.json()}

            hidden = client.get(
                f"/api/projects/{project_id}/overview",
                headers={"Authorization": f"Bearer {token_b}"},
            )
            assert hidden.status_code == 404
    finally:
        cleanup_db = db or SessionLocal()
        cleanup_db.execute(delete(UserToken).where(UserToken.user_id.in_([user_a_id, user_b_id])))
        if project is not None:
            cleanup_db.execute(delete(Project).where(Project.id == project_id))
        cleanup_db.execute(delete(User).where(User.id.in_([user_a_id, user_b_id])))
        cleanup_db.commit()
        cleanup_db.close()
