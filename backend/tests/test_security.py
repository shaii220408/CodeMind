import zipfile
from app.services.ingestion import safe_extract
import pytest

def test_zip_traversal_blocked(tmp_path):
    z=tmp_path/'bad.zip'
    with zipfile.ZipFile(z,'w') as f:f.writestr('../evil.txt','x')
    with pytest.raises(ValueError):safe_extract(str(z),str(tmp_path/'out'),1000)

def test_windows_zip_traversal_blocked(tmp_path):
    z=tmp_path/'windows.zip'
    with zipfile.ZipFile(z,'w') as f:f.writestr('..\\outside.py','x=1')
    with pytest.raises(ValueError):safe_extract(str(z),str(tmp_path/'out'),1000)

def test_only_supported_source_files_are_extracted(tmp_path):
    z=tmp_path/'repo.zip'
    with zipfile.ZipFile(z,'w') as f:
        f.writestr('src/main.py','print("ok")')
        f.writestr('secrets.env','TOKEN=not-for-indexing')
    out=tmp_path/'out'
    safe_extract(str(z),str(out),1000)
    assert (out/'src'/'main.py').read_text()=='print("ok")'
    assert not (out/'secrets.env').exists()

def test_archive_expansion_limit_applies_before_extracting(tmp_path):
    z=tmp_path/'large.zip'
    with zipfile.ZipFile(z,'w') as f:f.writestr('large.py','x'*100)
    with pytest.raises(ValueError,match='size limit'):
        safe_extract(str(z),str(tmp_path/'out'),10)
