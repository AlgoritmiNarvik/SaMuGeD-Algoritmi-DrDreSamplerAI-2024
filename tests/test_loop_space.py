import hashlib
import json

import pytest

from scripts.build_loop_space import _copy_render


def render_folder(root, payload):
    folder = root / 'phrase'
    folder.mkdir(parents=True)
    (folder / 'loop.wav').write_bytes(payload)
    entry = {'phrase_id': 'phrase', 'artifacts': [
        {'path': 'phrase/loop.wav', 'sha256': hashlib.sha256(payload).hexdigest()},
    ]}
    (root / 'manifest.json').write_text(json.dumps({'entries': [entry]}))


def test_shared_phrase_assets_must_be_identical(tmp_path):
    first, second, output = (tmp_path / name for name in ('first', 'second', 'space'))
    render_folder(first, b'canonical audio')
    render_folder(second, b'canonical audio')
    _copy_render(first, output)
    _copy_render(second, output)
    assert (output / 'audio/phrase/loop.wav').read_bytes() == b'canonical audio'
    (second / 'phrase/extra.txt').write_text('different asset set')
    with pytest.raises(ValueError, match='conflicting duplicate'):
        _copy_render(second, output)


def test_shared_phrase_with_different_audio_is_rejected(tmp_path):
    first, second, output = (tmp_path / name for name in ('first', 'second', 'space'))
    render_folder(first, b'canonical audio')
    render_folder(second, b'other audio')
    _copy_render(first, output)
    with pytest.raises(ValueError, match='conflicting duplicate'):
        _copy_render(second, output)
    assert (output / 'audio/phrase/loop.wav').read_bytes() == b'canonical audio'


def test_atlas_audio_binds_each_phrase_to_existing_rendered_cycle(tmp_path):
    from scripts.build_loop_space import attach_atlas_audio
    atlas = tmp_path / 'atlas'
    atlas.mkdir()
    (atlas / 'analysis.json').write_text(json.dumps({'snippets': {'phrase': []}}))
    (atlas / 'receipt.json').write_text(json.dumps({'outputs': {}}))
    root = tmp_path / 'audio/phrase'
    root.mkdir(parents=True)
    metadata = {'cycle_seconds': 3.5, 'period': {'period_beats': 7}, 'part': {'program': 25}}
    (root / 'metadata.json').write_text(json.dumps(metadata))
    (root / 'loop.wav').write_bytes(b'checked wave')
    (root / 'loop.mid').write_bytes(b'checked midi')
    attach_atlas_audio(atlas, tmp_path)
    packet = json.loads((atlas / 'analysis.json').read_text())
    assert packet['audio']['phrase']['wav'] == '../audio/phrase/loop.flac'
    receipt = json.loads((atlas / 'audio_receipt.json').read_text())
    assert receipt['bindings']['phrase']['loop.wav'] == hashlib.sha256(b'checked wave').hexdigest()
    html = (atlas / 'index.html').read_text()
    assert 'createOscillator' not in html
    assert 'playing.loop=true' in html


def test_atlas_requires_audio_for_every_displayed_phrase(tmp_path):
    from scripts.build_loop_space import attach_atlas_audio
    atlas = tmp_path / 'atlas'
    atlas.mkdir()
    (atlas / 'analysis.json').write_text(json.dumps({'snippets': {'missing': []}}))
    with pytest.raises(FileNotFoundError):
        attach_atlas_audio(atlas, tmp_path)


def test_popular_curation_preserves_original_ranking():
    from scripts.build_loop_space import curated_popular
    rows = [{'title_from_path': '2_Become_1', 'rank': 1}, {'title_from_path': 'Bohemian_Rhapsody', 'rank': 2}]
    featured = {'title_from_path': 'Schism', 'rank': 9, 'featured': True}
    curated = curated_popular(rows, featured)
    assert [r['title_from_path'] for r in curated] == ['Schism', 'Bohemian_Rhapsody']
    assert [r['rank'] for r in curated] == [1, 2]
    assert rows[0]['rank'] == 1 and featured['rank'] == 9


def test_atlas_attaches_source_drums_as_default(tmp_path):
    from scripts.build_loop_space import attach_atlas_audio
    atlas = tmp_path / 'atlas'
    atlas.mkdir()
    (atlas / 'analysis.json').write_text(json.dumps({'snippets': {'phrase': []}}))
    (atlas / 'receipt.json').write_text(json.dumps({'outputs': {}}))
    root = tmp_path / 'audio/phrase'
    root.mkdir(parents=True)
    (root / 'metadata.json').write_text(json.dumps({'cycle_seconds': 3.5, 'period': {'period_beats': 7}, 'part': {'program': 25}}))
    (root / 'loop.wav').write_bytes(b'wave')
    (root / 'loop.mid').write_bytes(b'midi')
    paired = tmp_path / 'audio/phrase-with-drums'
    paired.mkdir()
    (paired / 'metadata.json').write_bytes((root / 'metadata.json').read_bytes())
    (paired / 'loop.wav').write_bytes(b'paired wave')
    (paired / 'loop.mid').write_bytes(b'paired midi')
    attach_atlas_audio(atlas, tmp_path)
    packet = json.loads((atlas / 'analysis.json').read_text())
    assert packet['audio']['phrase']['default_mode'] == 'paired'
    assert packet['audio']['phrase']['with_drums']['midi'] == '../audio/phrase-with-drums/loop.mid'
