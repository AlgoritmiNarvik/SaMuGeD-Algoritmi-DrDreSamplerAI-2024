import json
from pathlib import Path
import pytest
from scripts.run_corpus_batches import batches, run
from samuged.dataset import file_digest


def test_batch_partition_preserves_every_source():
    assert list(batches(list(range(7)),3)) == [[0,1,2],[3,4,5],[6]]


def test_bounded_run_preserves_paths_and_rejects_changed_plan(tmp_path, monkeypatch):
    import scripts.run_corpus_batches as module
    archive=tmp_path/'pdmx-midi.tar.gz';archive.write_bytes(b'checked')
    (tmp_path/'acquisition.json').write_text(json.dumps({'pdmx-midi.tar.gz':{'sha256':file_digest(archive)}}))
    paths=['mid/artist/a.mid','mid/other/b.mid','mid/other/c.mid']
    (tmp_path/'pdmx_metadata.jsonl').write_text(''.join(json.dumps({'source_path':p})+'\n' for p in paths))
    def extraction(archive, output, **kwargs):
        assert kwargs['selected']==set(paths)
        for p in paths:
            target=output/p;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b'MIDI')
        return {'files':3,'bytes':12}
    seen=[]
    def build(source, output, cfg, **kwargs):
        seen.extend(p.relative_to(source).as_posix() for p in source.rglob('*.mid'))
        return {'source_files':len(list(source.rglob('*.mid')))}
    monkeypatch.setattr(module,'extract_archive',extraction)
    monkeypatch.setattr(module,'build',build)
    monkeypatch.setattr(module,'audit',lambda *a,**k:{'passed':True})
    monkeypatch.setattr(module.shutil,'disk_usage',lambda path:type('Space',(),{'free':100*1024**3})())
    result=run(tmp_path,batch_size=2)
    assert sorted(seen)==sorted(paths)
    assert result['completed_sources']==3
    assert result['status']=='extracted_and_batch_audited_pending_global_splits'
    with pytest.raises(ValueError,match='plan differs'):run(tmp_path,batch_size=3)


@pytest.mark.parametrize('kwargs',[{'batch_size':0},{'workers':5},{'reserve_gib':9}])
def test_invalid_run_budget_rejected(tmp_path,kwargs):
    with pytest.raises(ValueError,match='settings'):run(tmp_path,**kwargs)
