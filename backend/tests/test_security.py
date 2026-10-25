import stat
import zipfile

import pytest

from app.services.ingestion import safe_extract


def test_zip_traversal_blocked(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../evil.txt", "x")

    with pytest.raises(ValueError, match="Unsafe ZIP path"):
        safe_extract(str(archive), str(tmp_path / "out"), 1000)


def test_windows_zip_traversal_blocked(tmp_path):
    archive = tmp_path / "windows-traversal.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr(r"..\evil.py", "x")

    with pytest.raises(ValueError, match="Unsafe ZIP path"):
        safe_extract(str(archive), str(tmp_path / "out"), 1000)


def test_zip_symlink_blocked(tmp_path):
    archive = tmp_path / "symlink.zip"
    info = zipfile.ZipInfo("linked.py")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr(info, "target.py")

    with pytest.raises(ValueError, match="Unsafe ZIP path"):
        safe_extract(str(archive), str(tmp_path / "out"), 1000)


def test_zip_uncompressed_size_limit(tmp_path):
    archive = tmp_path / "large.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("large.py", "x" * 100)

    with pytest.raises(ValueError, match="size limit"):
        safe_extract(str(archive), str(tmp_path / "out"), 10)


def test_zip_file_count_limit(tmp_path):
    archive = tmp_path / "many-files.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("one.py", "1")
        output.writestr("two.py", "2")

    with pytest.raises(ValueError, match="file-count limit"):
        safe_extract(str(archive), str(tmp_path / "out"), 1000, max_files=1)