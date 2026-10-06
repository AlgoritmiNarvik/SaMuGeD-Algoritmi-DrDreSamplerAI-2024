from hashlib import sha256
import mido
from samuged.source_rights import scan


def test_notices_are_exact_evidence_not_composition_license(tmp_path):
    m=mido.MidiFile();t=mido.MidiTrack();m.tracks.append(t)
    t.append(mido.MetaMessage('copyright',text='Copyright 2001 Someone',time=12))
    t.append(mido.MetaMessage('lyrics',text='Do not collect lyrics'))
    p=tmp_path/'song.mid';m.save(p)
    row=scan(('key','song.mid',sha256(p.read_bytes()).hexdigest(),str(tmp_path)))
    assert row['scan_status']=='scanned'
    assert row['copyright_notices']==[dict(text='Copyright 2001 Someone',track=0,tick=12)]
    assert 'musical_work_license' not in row


def test_hash_mismatch_does_not_attach_notices(tmp_path):
    p=tmp_path/'song.mid';p.write_bytes(b'not midi')
    row=scan(('key','song.mid','wrong',str(tmp_path)))
    assert row['scan_status']=='hash_mismatch' and row['copyright_notices']==[]


def test_invalid_or_outside_source_remains_unavailable(tmp_path):
    p=tmp_path/'song.mid';p.write_bytes(b'not midi')
    row=scan(('key','song.mid',sha256(p.read_bytes()).hexdigest(),str(tmp_path)))
    assert row['scan_status']=='read_or_parse_error'
    assert scan(('key','../missing.mid',None,str(tmp_path)))['scan_status']=='read_or_parse_error'


def test_full_index_scan_keeps_work_license_unknown(tmp_path,monkeypatch):
    import json
    import shutil
    import pytest
    from test_catalog import setup_manifest
    from samuged.catalog import build_catalog
    from samuged.catalog_metadata import prepare as metadata_prepare,search
    from samuged.source_rights import prepare
    monkeypatch.setattr(shutil,'disk_usage',lambda _:shutil._ntuple_diskusage(10**12,0,10**12))
    manifest=setup_manifest(tmp_path);source=tmp_path/'original';source.mkdir()
    p=source/'song.mid';m=mido.MidiFile();t=mido.MidiTrack();m.tracks.append(t)
    t.append(mido.MetaMessage('copyright',text='Copyright Acme'));m.save(p)
    record=tmp_path/'records.jsonl';row=json.loads(record.read_text());row['source_path']='song.mid';row['source_sha256']=sha256(p.read_bytes()).hexdigest();record.write_text(json.dumps(row))
    catalog=tmp_path/'catalog.sqlite';build_catalog(manifest,catalog,max_output_mb=4,min_free_mb=0)
    metadata=tmp_path/'metadata.sqlite';metadata_prepare(catalog,metadata,max_output_mb=4)
    output=tmp_path/'rights.sqlite';result=prepare(metadata,catalog,output,{'local':source},workers=1)
    assert result['sources_with_notices']==1 and result['musical_work_license_unknown']==1
    matches=search(output,copyright_status='present_unverified',copyright_text='Acme',work_license_status='unknown')
    assert len(matches)==1 and matches[0]['musical_work_license'] is None
    assert matches[0]['copyright_notices'][0]['text']=='Copyright Acme'
    assert search(output,work_license_status='verified')==[]
    with pytest.raises(ValueError,match='rights scan'):search(metadata,copyright_status='absent')


def test_riff_midi_retains_original_file_hash(tmp_path):
    import io
    import struct
    m=mido.MidiFile();t=mido.MidiTrack();m.tracks.append(t);t.append(mido.MetaMessage('copyright',text='Notice'))
    stream=io.BytesIO();m.save(file=stream);raw=stream.getvalue()
    chunk=b'data'+struct.pack('<I',len(raw))+raw+(b'\0' if len(raw)%2 else b'')
    wrapped=b'RIFF'+struct.pack('<I',len(chunk)+4)+b'RMID'+chunk;p=tmp_path/'wrapped.mid';p.write_bytes(wrapped)
    row=scan(('key',p.name,sha256(wrapped).hexdigest(),str(tmp_path)))
    assert row['scan_status']=='scanned' and row['observed_sha256']==sha256(wrapped).hexdigest()
    assert row['copyright_notices'][0]['text']=='Notice'


def test_invalid_key_recovery_does_not_change_copyright_payload(tmp_path):
    from test_metadata_recovery import _smf,_meta,_end
    raw=_smf(_meta(0,0x59,b'\xff\xff')+_meta(10,0x02,b'Copyright unchanged')+_end())
    p=tmp_path/'invalid_key.mid';p.write_bytes(raw)
    row=scan(('key',p.name,sha256(raw).hexdigest(),str(tmp_path)))
    assert row['scan_status']=='scanned_metadata_repaired'
    assert row['copyright_notices']==[dict(text='Copyright unchanged',track=0,tick=10)]
    assert row['observed_sha256']==sha256(raw).hexdigest()


def test_portable_export_keeps_rights_and_notices(tmp_path,monkeypatch):
    import gzip
    import json
    from test_catalog_metadata import index
    from samuged.source_rights import prepare,export_records
    metadata,_=index(tmp_path,monkeypatch)
    rights=tmp_path/'rights.sqlite'
    prepare(metadata,tmp_path/'catalog.sqlite',rights,{'local':tmp_path},workers=1)
    output=tmp_path/'rights.jsonl.gz';receipt=export_records(rights,output)
    with gzip.open(output,'rt') as stream:row=json.loads(stream.readline())
    assert receipt['source_records']==1
    assert row['score_license_declaration']=='publicdomain'
    assert row['musical_work_license'] is None
    assert row['copyright_notice_status']=='unavailable'
    assert row['external_metadata_candidates']==[]


def test_opt_in_clipping_recovers_notice_without_changing_source(tmp_path):
    from test_metadata_recovery import _smf, _meta, _end
    raw = _smf(b'\x00\x90\x3c\xff'+_meta(12,0x02,b'Copyright original notice')+_end())
    path = tmp_path/'invalid_data.mid'; path.write_bytes(raw)
    task = ('key',path.name,sha256(raw).hexdigest(),str(tmp_path))
    assert scan(task)['scan_status'] == 'read_or_parse_error'
    recovered = scan(task,allow_clipped_data=True)
    assert recovered['scan_status'] == 'scanned_clipped'
    assert recovered['copyright_notices'] == [dict(text='Copyright original notice',track=0,tick=12)]
    assert recovered['observed_sha256'] == sha256(raw).hexdigest()
    assert path.read_bytes() == raw
    assert 'metadata_read_only' in recovered['recovery_scope']


def test_clipping_does_not_recover_truncated_metadata(tmp_path):
    from test_metadata_recovery import _smf
    raw = _smf(b'\x00\xff\x02\x10short')
    path = tmp_path/'truncated.mid';path.write_bytes(raw)
    result = scan(('key',path.name,sha256(raw).hexdigest(),str(tmp_path)),allow_clipped_data=True)
    assert result['scan_status'] == 'read_or_parse_error'
    assert result['copyright_notices'] == []


def test_combined_channel_and_key_errors_remain_unavailable(tmp_path):
    from test_metadata_recovery import _smf, _meta, _end
    raw = _smf(b'\x00\x90\x3c\xff'+_meta(0,0x59,b'\xff\xff')+_meta(12,0x02,b'Original notice')+_end())
    path=tmp_path/'both.mid';path.write_bytes(raw)
    row=scan(('key',path.name,sha256(raw).hexdigest(),str(tmp_path)),allow_clipped_data=True)
    assert row['scan_status']=='read_or_parse_error'
    assert row['copyright_notices']==[]
    assert path.read_bytes()==raw
