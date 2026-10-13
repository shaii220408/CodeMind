import subprocess

import pytest

from app.services.repository import clone_repository


def test_clone_uses_shallow_no_submodule_https_command(tmp_path,monkeypatch):
    commands=[]
    def fake_run(command,**kwargs):
        commands.append(command)
        (tmp_path/"checkout").mkdir()
        return subprocess.CompletedProcess(command,0)
    monkeypatch.setattr(subprocess,"run",fake_run)

    clone_repository("https://github.com/example/repo.git",str(tmp_path/"checkout"))

    assert "--depth" in commands[0]
    assert "--no-recurse-submodules" in commands[0]
    assert "https://github.com/example/repo.git" in commands[0]


def test_clone_rejects_unallowlisted_hosts(tmp_path):
    with pytest.raises(ValueError,match="public HTTPS"):
        clone_repository("https://internal.example/repo.git",str(tmp_path/"checkout"))
