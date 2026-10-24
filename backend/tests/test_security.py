import zipfile
from app.services.ingestion import safe_extract
import pytest

def test_zip_traversal_blocked(tmp_path):
    z=tmp_path/'bad.zip'
    with zipfile.ZipFile(z,'w') as f:f.writestr('../evil.txt','x')
    with pytest.raises(ValueError):safe_extract(str(z),str(tmp_path/'out'),1000)
