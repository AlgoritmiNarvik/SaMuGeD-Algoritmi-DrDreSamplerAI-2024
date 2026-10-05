"""Budgeted corpus acquisition with checksums and bounded archive extraction."""
from __future__ import annotations

from hashlib import new as hash_new
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tarfile
import tempfile
from urllib.request import urlopen
from urllib.parse import urlsplit
import zipfile


def download(url, output: Path, *, checksum, max_bytes, reserve_bytes=2*1024**3):
    """Download an explicitly selected HTTPS asset. No overwrite or automatic discovery."""
    if urlsplit(url).scheme != 'https':
        raise ValueError('HTTPS source required')
    algorithm, expected = checksum.split(':',1)
    if algorithm not in {'sha256','md5'}:
        raise ValueError('unsupported checksum')
    if max_bytes <= 0 or reserve_bytes < 0:
        raise ValueError('invalid storage budget')
    output.parent.mkdir(parents=True,exist_ok=True)
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    if shutil.disk_usage(output.parent).free < max_bytes + reserve_bytes:
        raise ValueError('insufficient storage reserve')
    h=hash_new(algorithm);strong=hash_new('sha256');count=0
    with tempfile.TemporaryDirectory(prefix='samuged-download-',dir=output.parent) as tmp:
        target=Path(tmp)/'asset'
        with urlopen(url,timeout=60) as response,target.open('wb') as stream:
            if urlsplit(response.url).scheme != 'https':
                raise ValueError('insecure redirect')
            # ASVS 5.2.1: enforce actual streamed bytes, not only Content-Length.
            while chunk := response.read(1024*1024):
                count += len(chunk)
                if count > max_bytes:
                    raise ValueError('download exceeds byte budget')
                stream.write(chunk);h.update(chunk);strong.update(chunk)
        if h.hexdigest()!=expected.lower():
            raise ValueError('checksum mismatch')
        os.link(target,output)
    return {'url':url,'bytes':count,'upstream_checksum':checksum,'sha256':strong.hexdigest()}


def extract_archive(archive: Path, output: Path, *, max_bytes, max_files,
                    selected=None, suffixes=('.mid','.midi','.json','.csv','.txt')):
    """Extract selected regular files into a new directory, without links or traversal."""
    if max_bytes <= 0 or max_files <= 0:
        raise ValueError('invalid extraction budget')
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(output.parent).free < max_bytes+2*1024**3:
        raise ValueError('insufficient extraction reserve')
    total=count=inspected=0
    seen=set()
    with tempfile.TemporaryDirectory(prefix='samuged-extract-',dir=output.parent) as tmp:
        root=Path(tmp)/'files';root.mkdir()
        def copy(name,size,reader):
            nonlocal total,count,inspected
            inspected+=1
            if inspected>1_000_000:
                raise ValueError('archive entry limit exceeded')
            p=PurePosixPath(name)
            # ASVS 5.2.3/5.2.5: reject traversal and links before extracting any bytes.
            if p.is_absolute() or '..' in p.parts or '\\' in name or ':' in name:
                raise ValueError('unsafe archive path')
            normalized=p.as_posix()
            if normalized in seen:
                raise ValueError('duplicate archive entry')
            seen.add(normalized)
            if p.suffix.lower() not in suffixes or (selected is not None and normalized not in selected):
                return
            if size < 0 or count+1>max_files or total+size>max_bytes:
                raise ValueError('unpacked archive exceeds budget')
            target=root.joinpath(*p.parts);target.parent.mkdir(parents=True,exist_ok=True)
            actual=0
            with reader() as src,target.open('xb') as dst:
                while chunk:=src.read(1024*1024):
                    actual+=len(chunk)
                    if actual>size:
                        raise ValueError('archive entry exceeds declared size')
                    dst.write(chunk)
            if actual!=size:
                raise ValueError('truncated archive entry')
            total+=actual;count+=1
        if zipfile.is_zipfile(archive):
            with zipfile.ZipFile(archive) as z:
                for item in z.infolist():
                    mode=item.external_attr>>16
                    if stat.S_ISLNK(mode):
                        raise ValueError('archive links are not allowed')
                    if stat.S_IFMT(mode) not in (0,stat.S_IFREG,stat.S_IFDIR):
                        raise ValueError('archive special entries are not allowed')
                    if not item.is_dir():
                        copy(item.filename,item.file_size,lambda item=item:z.open(item))
        else:
            with tarfile.open(archive,'r|*') as t:
                for item in t:
                    if item.isdir():continue
                    if not item.isfile():
                        raise ValueError('archive links and special entries are not allowed')
                    copy(item.name,item.size,lambda item=item:t.extractfile(item))
        if not count:
            raise ValueError('no selected files in archive')
        # The destination must be fresh. No partial corpus is exposed on failure.
        if output.exists():raise FileExistsError(output)
        root.rename(output)
    return {'files':count,'bytes':total,'inspected_entries':inspected}
