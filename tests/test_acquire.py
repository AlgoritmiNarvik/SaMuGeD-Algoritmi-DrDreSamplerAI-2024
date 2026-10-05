from pathlib import Path
import zipfile
import pytest
from samuged.acquire import extract_archive


def archive(tmp_path,files):
    path=tmp_path/'input.zip'
    with zipfile.ZipFile(path,'w') as z:
        for name,data in files:z.writestr(name,data)
    return path


def test_selected_members_only(tmp_path):
    path=archive(tmp_path,[('a.mid',b'MThd'),('b.mid',b'MThd'),('a.pdf',b'pdf')])
    out=tmp_path/'files'
    result=extract_archive(path,out,max_bytes=8,max_files=1,selected={'a.mid'})
    assert result['files']==1 and [p.name for p in out.iterdir()]==['a.mid']


@pytest.mark.parametrize('name',['../bad.mid','/bad.mid','a\\bad.mid','C:bad.mid'])
def test_traversal_rejected_even_when_not_selected(tmp_path,name):
    path=archive(tmp_path,[(name,b'x')]);out=tmp_path/'files'
    with pytest.raises(ValueError,match='unsafe'):
        extract_archive(path,out,max_bytes=100,max_files=10,selected={'good.mid'})
    assert not out.exists()


def test_unpack_budget_leaves_no_partial_output(tmp_path):
    path=archive(tmp_path,[('a.mid',b'1234'),('b.mid',b'1234')]);out=tmp_path/'files'
    with pytest.raises(ValueError,match='budget'):
        extract_archive(path,out,max_bytes=7,max_files=10)
    assert not out.exists()


def test_zip_symlink_rejected(tmp_path):
    path=tmp_path/'input.zip';entry=zipfile.ZipInfo('a.mid');entry.external_attr=0o120777<<16
    with zipfile.ZipFile(path,'w') as z:z.writestr(entry,'elsewhere')
    with pytest.raises(ValueError,match='links'):
        extract_archive(path,tmp_path/'files',max_bytes=100,max_files=10)


def test_download_checksum_failure_is_not_published(tmp_path,monkeypatch):
    from io import BytesIO
    from samuged import acquire
    class Response(BytesIO):
        url='https://example.org/asset'
    monkeypatch.setattr(acquire,'urlopen',lambda *a,**k:Response(b'bad'))
    with pytest.raises(ValueError,match='checksum'):
        acquire.download('https://example.org/asset',tmp_path/'asset',checksum='sha256:'+'0'*64,max_bytes=10,reserve_bytes=0)
    assert not (tmp_path/'asset').exists()


def test_download_actual_size_limit(tmp_path,monkeypatch):
    from io import BytesIO
    from samuged import acquire
    class Response(BytesIO):
        url='https://example.org/asset'
    monkeypatch.setattr(acquire,'urlopen',lambda *a,**k:Response(b'123456'))
    with pytest.raises(ValueError,match='budget'):
        acquire.download('https://example.org/asset',tmp_path/'asset',checksum='sha256:'+'0'*64,max_bytes=5,reserve_bytes=0)
    assert not (tmp_path/'asset').exists()


def test_tar_link_rejected(tmp_path):
    import tarfile
    path=tmp_path/'input.tar.gz'
    with tarfile.open(path,'w:gz') as t:
        entry=tarfile.TarInfo('a.mid');entry.type=tarfile.SYMTYPE;entry.linkname='/tmp/no'
        t.addfile(entry)
    with pytest.raises(ValueError,match='links'):
        extract_archive(path,tmp_path/'files',max_bytes=100,max_files=10)
