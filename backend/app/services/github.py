"""Bounded, unauthenticated GitHub repository snapshot downloads."""

import json
import re
import shutil
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

GITHUB_API = "https://api.github.com"
ALLOWED_ARCHIVE_HOSTS = {"github.com", "codeload.github.com"}
REPOSITORY_SIZE_LIMIT_MB = 200
ARCHIVE_SIZE_LIMIT_MB = 100
API_TIMEOUT_SECONDS = 10
ARCHIVE_TIMEOUT_SECONDS = 60


class GitHubImportError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(message)


def normalize_public_github_url(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
        segments = [segment for segment in parsed.path.strip("/").split("/") if segment]
        valid_host = parsed.hostname == "github.com" and parsed.port is None and parsed.username is None and parsed.password is None
    except ValueError:
        valid_host = False
        segments = []
    if not valid_host or parsed.scheme != "https" or parsed.query or parsed.fragment or len(segments) != 2:
        raise GitHubImportError(422, "Use a public HTTPS GitHub repository URL such as https://github.com/owner/repository.")
    owner, repository = segments
    if repository.endswith(".git"):
        repository = repository[:-4]
    if any(not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", item) or item in {".", ".."} for item in (owner, repository)):
        raise GitHubImportError(422, "The GitHub owner or repository path is invalid.")
    return f"https://github.com/{owner}/{repository}"


def validate_branch(value: str | None) -> str | None:
    if value is None:
        return None
    branch = value.strip()
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}", branch)
        or ".." in branch
        or "//" in branch
        or branch.endswith(("/", "."))
        or "@{" in branch
        or any(part.startswith(".") or part.endswith(".lock") for part in branch.split("/"))
    ):
        raise GitHubImportError(422, "The branch name is invalid.")
    return branch


def _safe_error(error: Exception) -> GitHubImportError:
    if isinstance(error, urllib.error.HTTPError):
        if error.code == 404:
            return GitHubImportError(404, "The public GitHub repository or branch was not found.")
        if error.code in {403, 429}:
            return GitHubImportError(503, "GitHub rate limited or denied this request. Retry later.")
        return GitHubImportError(502, "GitHub could not provide the repository snapshot.")
    if isinstance(error, (TimeoutError, urllib.error.URLError)):
        return GitHubImportError(504, "GitHub did not respond before the import timeout.")
    return GitHubImportError(502, "GitHub repository import failed.")


def _json(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "CodeMind-repository-sync"},
    )
    try:
        with urllib.request.urlopen(request, timeout=API_TIMEOUT_SECONDS) as response:
            payload = response.read(1024 * 1024 + 1)
        if len(payload) > 1024 * 1024:
            raise GitHubImportError(502, "GitHub returned an oversized metadata response.")
        return json.loads(payload.decode("utf-8"))
    except GitHubImportError:
        raise
    except Exception as error:
        raise _safe_error(error) from None


class _SafeArchiveRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        host = urlsplit(newurl).hostname
        if host not in ALLOWED_ARCHIVE_HOSTS or urlsplit(newurl).scheme != "https":
            raise GitHubImportError(502, "GitHub archive redirected to an unsupported host.")
        return super().redirect_request(request, fp, code, message, headers, newurl)


def download_public_snapshot(repository_url: str, branch: str | None, destination: str, max_files: int) -> dict:
    """Download and safely extract one public branch snapshot; return source metadata."""
    from app.services.ingestion import safe_extract

    normalized = normalize_public_github_url(repository_url)
    branch = validate_branch(branch)
    parsed = urlsplit(normalized)
    owner, repository = parsed.path.strip("/").split("/", 1)
    api_repo = f"{GITHUB_API}/repos/{owner}/{repository}"
    metadata = _json(api_repo)
    size_kb = metadata.get("size")
    if not isinstance(size_kb, int) or size_kb < 0:
        raise GitHubImportError(502, "GitHub repository size metadata was invalid.")
    if size_kb > REPOSITORY_SIZE_LIMIT_MB * 1024:
        raise GitHubImportError(413, "The GitHub repository exceeds CodeMind's 200 MB limit.")

    selected_branch = validate_branch(branch or metadata.get("default_branch"))
    if not selected_branch:
        raise GitHubImportError(502, "GitHub did not provide a valid default branch.")
    encoded_branch = urllib.parse.quote(selected_branch, safe="")
    commit = _json(f"{api_repo}/commits/{encoded_branch}")
    commit_sha = commit.get("sha")
    if not isinstance(commit_sha, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", commit_sha):
        raise GitHubImportError(502, "GitHub returned an invalid commit identifier.")

    archive_url = f"{api_repo}/zipball/{commit_sha}"
    request = urllib.request.Request(archive_url, headers={"User-Agent": "CodeMind-repository-sync"})
    destination_path = Path(destination)
    destination_path.mkdir(parents=True, exist_ok=True)
    archive_path = None
    try:
        opener = urllib.request.build_opener(_SafeArchiveRedirect())
        with tempfile.NamedTemporaryFile(prefix="codemind-github-", suffix=".zip", delete=False) as output:
            archive_path = Path(output.name)
            with opener.open(request, timeout=ARCHIVE_TIMEOUT_SECONDS) as response:
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > ARCHIVE_SIZE_LIMIT_MB * 1024 * 1024:
                    raise GitHubImportError(413, "The downloaded GitHub archive exceeds CodeMind's 100 MB limit.")
                total = 0
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    total += len(block)
                    if total > ARCHIVE_SIZE_LIMIT_MB * 1024 * 1024:
                        raise GitHubImportError(413, "The downloaded GitHub archive exceeds CodeMind's 100 MB limit.")
                    output.write(block)
        safe_extract(str(archive_path), str(destination_path), ARCHIVE_SIZE_LIMIT_MB * 1024 * 1024, max_files)
    except GitHubImportError:
        raise
    except Exception as error:
        raise _safe_error(error) from None
    finally:
        if archive_path:
            archive_path.unlink(missing_ok=True)

    roots = list(destination_path.iterdir())
    if len(roots) != 1 or not roots[0].is_dir() or roots[0].is_symlink():
        raise GitHubImportError(502, "GitHub returned an unexpected archive layout.")
    wrapper = roots[0]
    for child in list(wrapper.iterdir()):
        child.rename(destination_path / child.name)
    wrapper.rmdir()
    return {"repository_url": normalized, "branch": selected_branch, "commit_sha": commit_sha.lower()}
