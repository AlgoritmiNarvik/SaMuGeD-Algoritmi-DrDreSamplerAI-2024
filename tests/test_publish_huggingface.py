import hashlib
import json
from types import SimpleNamespace

import pytest

from scripts.publish_huggingface import parse_args, public_files, run


class FakeApi:
    def __init__(self, owner='owner'):
        self.owner, self.calls = owner, []

    def whoami(self):
        return {'name': self.owner}

    def create_repo(self, *args, **kwargs):
        self.calls.append(('create_repo', args, kwargs))

    def upload_folder(self, **kwargs):
        self.calls.append(('upload_folder', (), kwargs))
        return SimpleNamespace(oid='abc123', repo_url='https://huggingface.co/datasets/owner/samuged-recurring-phrases')


@pytest.fixture
def folder(tmp_path):
    root = tmp_path/'expansion'
    (root/'data'/'pdmx_melodic').mkdir(parents=True)
    (root/'data'/'pdmx_melodic'/'part-00000.parquet').write_bytes(b'parquet')
    (root/'evidence').mkdir()
    (root/'evidence'/'expansion_build_receipt.json').write_text('{}')
    (root/'.cache').mkdir()
    (root/'.cache'/'ignored').write_text('x')
    return root


def args_for(tmp_path, folder, *extra):
    return parse_args(['--owner', 'owner', '--dataset', str(folder), '--dataset-only',
                       '--receipt', str(tmp_path/'receipt.json'), *extra])


def test_dataset_only_preview_does_not_upload(tmp_path, folder, capsys):
    api = FakeApi()
    preview = run(args_for(tmp_path, folder), api)
    assert api.calls == [] and not (tmp_path/'receipt.json').exists()
    assert preview['dataset']['files'] == 2 and preview['dataset']['mode'] == 'add_or_replace_only'
    assert json.loads(capsys.readouterr().out)['dataset']['bytes'] == len(b'parquet') + 2


def test_dataset_only_publish_adds_files_without_deleting(tmp_path, folder):
    api = FakeApi()
    receipt = run(args_for(tmp_path, folder, '--publish', '--path-in-repo', 'expansion'), api)
    assert [c[0] for c in api.calls] == ['upload_folder']  # the existing repository is not recreated
    call = api.calls[0][2]
    assert 'delete_patterns' not in call and call['repo_type'] == 'dataset'
    assert call['repo_id'] == 'owner/samuged-recurring-phrases' and call['path_in_repo'] == 'expansion'
    assert call['allow_patterns'] == ['data/pdmx_melodic/part-00000.parquet', 'evidence/expansion_build_receipt.json']
    stored = json.loads((tmp_path/'receipt.json').read_text())
    assert stored == receipt and stored['dataset']['commit'] == 'abc123'
    entry = stored['dataset']['files']['expansion/data/pdmx_melodic/part-00000.parquet']
    assert entry == dict(bytes=7, sha256=hashlib.sha256(b'parquet').hexdigest())


def test_dataset_only_defaults_to_the_repository_root(tmp_path, folder):
    api = FakeApi()
    run(args_for(tmp_path, folder, '--publish'), api)
    assert api.calls[0][2]['path_in_repo'] is None


def test_owner_mismatch_is_refused(tmp_path, folder):
    with pytest.raises(ValueError, match='authenticated account'):
        run(args_for(tmp_path, folder, '--publish'), FakeApi(owner='someone'))


def test_release_mode_still_requires_a_readme(tmp_path, folder):
    args = parse_args(['--owner', 'owner', '--dataset', str(folder), '--receipt', str(tmp_path/'r.json')])
    with pytest.raises(ValueError, match='README'):
        run(args, FakeApi())
    assert public_files(folder, dataset=True, require_readme=False) == [
        'data/pdmx_melodic/part-00000.parquet', 'evidence/expansion_build_receipt.json']


def test_invalid_combinations_are_refused(tmp_path, folder):
    with pytest.raises(SystemExit):
        args_for(tmp_path, folder, '--space', str(folder))
    with pytest.raises(SystemExit):
        args_for(tmp_path, folder, '--path-in-repo', '../outside')
    with pytest.raises(SystemExit):
        parse_args(['--owner', 'o', '--dataset', str(folder), '--receipt', 'r.json', '--path-in-repo', 'x'])
