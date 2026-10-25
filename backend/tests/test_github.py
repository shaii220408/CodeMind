import pytest

from app.services.github import GitHubImportError, normalize_public_github_url, validate_branch


@pytest.mark.parametrize("value,expected", [
    ("https://github.com/acme/widget", "https://github.com/acme/widget"),
    ("https://github.com/acme/widget.git", "https://github.com/acme/widget"),
])
def test_public_github_url_is_normalized(value, expected):
    assert normalize_public_github_url(value) == expected


@pytest.mark.parametrize("value", [
    "http://github.com/acme/widget", "https://github.com.evil.test/acme/widget",
    "https://user:pass@github.com/acme/widget", "https://github.com/acme/widget?token=x",
    "https://github.com/acme/widget/tree/main", "https://127.0.0.1/acme/widget",
])
def test_non_repository_or_non_public_github_urls_are_rejected(value):
    with pytest.raises(GitHubImportError):
        normalize_public_github_url(value)


@pytest.mark.parametrize("branch", ["main", "release/2.1", "feature-code"])
def test_valid_git_branch_names(branch):
    assert validate_branch(branch) == branch


@pytest.mark.parametrize("branch", ["../main", "main//x", "-option", "name.lock", "x@{y}"])
def test_unsafe_git_branch_names_are_rejected(branch):
    with pytest.raises(GitHubImportError):
        validate_branch(branch)


def test_repository_size_preflight_rejects_large_repository(monkeypatch, tmp_path):
    from app.services import github

    monkeypatch.setattr(github, "_json", lambda url: {"size": 200 * 1024 + 1})
    with pytest.raises(GitHubImportError) as error:
        github.download_public_snapshot("https://github.com/acme/widget", None, str(tmp_path), 10)
    assert error.value.status_code == 413
