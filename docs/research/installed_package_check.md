# Installed package check

The extraction package was built from local commit `500df27473e84f90d245085021286221843129c7` and installed into a temporary Python environment outside the repository. The test stripped Python path overrides and checked the installed module hashes against the committed source. Only declared runtime dependencies were installed.

The eight inputs contained six planted melodic cases, a separate drum loop and one recoverable invalid key signature. Each of `reference`, `aligned_closed` and `aligned_melody` processed all eight sources and passed full source, excerpt and selection reextraction auditing. Only the intended invalid-key input carried a repair receipt. The drum-only input produced percussion output and no melodic candidate. Input bytes were unchanged after all three builds.

| Algorithm | Melodic candidates | Percussion candidates | Source errors | Audit failures |
| --- | ---: | ---: | ---: | ---: |
| reference | 8 | 1 | 0 | 0 |
| aligned_closed | 10 | 1 | 0 | 0 |
| aligned_melody | 10 | 1 | 0 | 0 |

The preferred receipt is `research_local/packaging_smoke_v05/completion.json`. Its 236 payloads include the exact test driver, committed package snapshot, generated inputs, wheel metadata, command logs and per-algorithm datasets. Root verification checked every payload hash and the test-driver binding. The report SHA256 is `5dabce87e5980aeffdcf6f08a16436a18e110419563785abb7da1c78db8462e6`. The driver SHA256 is `c5c83f027f57d5154c986f988ff1729a9d69c3c7a43b0822fb806bac4de813a9`.

```sh
source .venv/bin/activate
python scripts/smoke_wheel.py \
  --revision 500df27 \
  --output research_local/my_package_check \
  --algorithms reference aligned_closed aligned_melody
```

The command uses the local `uv` cache in offline mode and requires a new output directory. Its environment was CPython 3.12.13 with Mido 1.3.3. The receipt records the actual installer and wheel build metadata. Wheel byte reproducibility is not claimed because build timestamps and the installed build backend can vary. This is an installation and CLI check on synthetic fixtures, not a real-corpus quality evaluation.

The historical v02 attempt reproduced an optional Git probe printing a fatal diagnostic outside a checkout despite a successful build. The later implementation suppresses that optional diagnostic and the smoke test rejects its recurrence. v03 passed before the driver itself was added to the artifact receipt; both earlier directories remain unchanged.

The preferred v05 check includes the Unicode-safe audit readers and trailing-newline-safe smoke runner. Root checked all 236 payload hashes. Completion SHA256 is `8cbabd1a9a6b0df4a5ef55f09f0d451ecfbf74ad69a51c27dced617fced3c2ca`. The actual Unicode separator regression is separately exercised by `tests/test_jsonl_unicode.py`; these eight wheel fixtures are unchanged from v04.
