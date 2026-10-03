# POP909 part-role cohort inputs

This directory is a local external evaluation input cohort. It is separate from the Lakh dataset and is not a replacement or addition to the Lakh release. The preparation fetched only the selected song MIDI files. It did not fetch audio, accompaniment variants or the full POP909 archive and it did not run a detector or assign role labels.

## Upstream and license

The source is the official [music-x-lab/POP909-Dataset repository](https://github.com/music-x-lab/POP909-Dataset/tree/d83e6edba6872a704f5d3b8b32f5cb540088dae6). The immutable source commit is `d83e6edba6872a704f5d3b8b32f5cb540088dae6`. The repository [README](https://github.com/music-x-lab/POP909-Dataset/blob/d83e6edba6872a704f5d3b8b32f5cb540088dae6/README.md) describes each `POP909/<id>/<id>.mid` arrangement as containing `MELODY`, `BRIDGE` and `PIANO` tracks. The repository [LICENSE](https://github.com/music-x-lab/POP909-Dataset/blob/d83e6edba6872a704f5d3b8b32f5cb540088dae6/LICENSE) is MIT and is retained as an upstream reference. Use of the underlying musical material remains subject to the upstream terms and any applicable rights.

Each source URL is pinned to the commit:

```text
https://raw.githubusercontent.com/music-x-lab/POP909-Dataset/d83e6edba6872a704f5d3b8b32f5cb540088dae6/POP909/{song_id}/{song_id}.mid
```

## Frozen cohort

The reproducible preparer is [`scripts/prepare_pop909_role.py`](../../scripts/prepare_pop909_role.py). It queried only the official Git tree metadata, ranked song IDs with `SHA256("samuged-pop909-role-v1\\0" + song_id)`, excluded the six previously inspected IDs `065`, `284`, `310`, `422`, `449` and `464` and wrote the selection manifest before requesting any selected MIDI bytes.

The selected cohort is in [`research_local/external/pop909_role_v01`](../../research_local/external/pop909_role_v01):

- [`selection_manifest.json`](../../research_local/external/pop909_role_v01/selection_manifest.json), schema `samuged-pop909-role-selection-v1`, 903 eligible IDs and 180 selected IDs.
- The first 60 ranked IDs are `development`; the next 120 are `heldout`.
- Selection manifest file SHA256: `298475990757d9e8574e121f58dff14aaf35d5696963e6baa143de917db4d956`.
- Canonical selection payload SHA256 recorded inside the manifest: `653838420dedfebda9039fd63371e45da5eb8f783dfa6a967ed88dc848b2b244`.
- The six excluded IDs are not present in the selected records.

The selected source files and post-download parse metadata are in [`source_manifest.json`](../../research_local/external/pop909_role_v01/source_manifest.json), schema `samuged-pop909-role-v1`. Each record contains the song ID, frozen split, upstream path and URL, local MIDI path, byte count and SHA256, strict parser result, ticks per beat and the source part names, programs, channels, tracks, drum flags and note counts. The source manifest records the exact upstream role names after selection; these are source metadata, not human annotation labels.

Preparation completed with 180 downloaded files, 2,257,708 total bytes and zero strict parser errors. The source roles are present once per song as `MELODY`, `BRIDGE` and `PIANO`. Their cohort-wide note counts are 60,646, 49,175 and 193,777 respectively. No source was substituted after an error. The canonical source manifest hash recorded in the receipt is `1983c752da244e22ee5e61635ff061f3f18b413bc9dfade318ce6af280e00832`; the JSON file SHA256 is `076bbad7b4cecb1a274c5bb5148e5b34b44ecf222b2964902541dce2d9992f67`.

[`download_receipt.json`](../../research_local/external/pop909_role_v01/download_receipt.json) records the 100 MiB download cap, selection hash, source manifest hash and the boundary that this artifact is an external source cohort only. Its file SHA256 is `66d8900ae247eaec76dc6a6c164fa7fdfb8dc01c0052cb150398dc24a77e083e`.

The six excluded source files remain under [`research_local/external/theme_transformer/pop909_original`](../../research_local/external/theme_transformer/pop909_original) with their existing receipt. They are intentionally outside this new development and heldout cohort.

## Use boundary

The `MELODY`, `BRIDGE` and `PIANO` names define source part roles for a later evaluation design. They do not establish that a detector selected a musically correct part and they do not provide phrase or salience labels. Freeze detector configuration and any reranking weights before opening heldout role metadata. Keep the development and heldout IDs separate when recording later results.
