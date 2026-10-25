import os
import subprocess
from pathlib import Path

from app.core.config import settings
from app.schemas.schemas import ProjectCreate


def clone_repository(repository_url: str, destination: str):
    """Clone an allowlisted public HTTPS repository without executing repo hooks."""
    # Reuse schema validation here because Celery jobs can be queued without a
    # client passing through request validation in the future.
    validated=ProjectCreate(name="repository validation",repository_url=repository_url).repository_url
    if not validated:
        raise ValueError("Repository URL is required")
    env=os.environ.copy()
    env.update({"GIT_TERMINAL_PROMPT":"0","GIT_CONFIG_NOSYSTEM":"1","GIT_CONFIG_GLOBAL":os.devnull})
    try:
        result=subprocess.run(
            ["git","-c","http.followRedirects=false","clone","--depth","1","--no-tags","--single-branch","--no-recurse-submodules","--",validated,destination],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            timeout=settings.repository_clone_timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Repository clone exceeded its configured timeout") from exc
    except OSError as exc:
        raise RuntimeError("Git is unavailable in the indexing worker") from exc
    if result.returncode:
        raise RuntimeError(f"Repository clone failed with exit code {result.returncode}")
    if not Path(destination).is_dir():
        raise RuntimeError("Repository clone did not produce a working tree")
