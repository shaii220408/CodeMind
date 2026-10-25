from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.routes import owned_project


class ProjectLookup:
    def __init__(self, projects):
        self.projects = projects

    def scalar(self, statement):
        compiled = statement.compile()
        assert "projects.owner_id" in str(compiled)
        params = compiled.params
        project_id = next(value for value in params.values() if value in self.projects)
        owner_id = next(value for key, value in params.items() if key.startswith("owner_id"))
        project = self.projects.get(project_id)
        return project if project and project.owner_id == owner_id else None


def test_project_owner_can_access_project():
    project = SimpleNamespace(id="project-1", owner_id="user-a")
    db = ProjectLookup({project.id: project})
    assert owned_project(db, SimpleNamespace(id="user-a"), "project-1") is project


def test_other_user_cannot_access_project():
    project = SimpleNamespace(id="project-1", owner_id="user-a")
    db = ProjectLookup({project.id: project})
    with pytest.raises(HTTPException) as exc:
        owned_project(db, SimpleNamespace(id="user-b"), "project-1")
    assert exc.value.status_code == 404
