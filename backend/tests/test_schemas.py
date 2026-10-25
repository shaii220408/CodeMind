import pytest
from pydantic import ValidationError

from app.schemas.schemas import ProjectCreate


def test_repository_url_accepts_public_allowlisted_https_host():
    project=ProjectCreate(name="repo",repository_url="https://github.com/example/project.git")
    assert project.repository_url=="https://github.com/example/project.git"


@pytest.mark.parametrize("url",[
    "http://github.com/example/project",
    "https://user:token@github.com/example/project",
    "https://attacker.example/example/project",
    "https://github.com/example/../private",
])
def test_repository_url_rejects_unsafe_sources(url):
    with pytest.raises(ValidationError):
        ProjectCreate(name="repo",repository_url=url)


def test_project_name_rejects_whitespace_only():
    with pytest.raises(ValidationError):
        ProjectCreate(name="   ")
