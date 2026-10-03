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
