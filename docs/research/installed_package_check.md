# Installed package check

The extraction package was built from local commit `b855b6b610f4676246ddefb37374cc2489629ec6` and installed into a temporary Python environment outside the repository. The test stripped Python path overrides and checked the installed module hashes against the committed source. Only declared runtime dependencies were installed.

The eight inputs contained six planted melodic cases, a separate drum loop and one recoverable invalid key signature. Each of `reference`, `aligned_closed` and `aligned_melody` processed all eight sources and passed full source, excerpt and selection reextraction auditing. Only the intended invalid-key input carried a repair receipt. The drum-only input produced percussion output and no melodic candidate. Input bytes were unchanged after all three builds.

| Algorithm | Melodic candidates | Percussion candidates | Source errors | Audit failures |
| --- | ---: | ---: | ---: | ---: |
| reference | 8 | 1 | 0 | 0 |
| aligned_closed | 10 | 1 | 0 | 0 |
| aligned_melody | 10 | 1 | 0 | 0 |

The preferred receipt is `research_local/packaging_smoke_v04/completion.json`. Its 236 payloads include the exact test driver, committed package snapshot, generated inputs, wheel metadata, command logs and per-algorithm datasets. Root verification checked every payload hash and the test-driver binding. The report SHA256 is `4aec7e385819e8461b04931b5fbc35f6ef7ee9d875158639767b6491a33efbde`. The driver SHA256 is `49a76645c88af06e09f91503da408bfdcc5a9832a733f2114cca71c2ba9ca03e`.

```sh
source .venv/bin/activate
python scripts/smoke_wheel.py \
  --revision b855b6b \
  --output research_local/my_package_check \
  --algorithms reference aligned_closed aligned_melody
```

The command uses the local `uv` cache in offline mode and requires a new output directory. Its environment was CPython 3.12.13 with Mido 1.3.3. The receipt records the actual installer and wheel build metadata. Wheel byte reproducibility is not claimed because build timestamps and the installed build backend can vary. This is an installation and CLI check on synthetic fixtures, not a real-corpus quality evaluation.

The historical v02 attempt reproduced an optional Git probe printing a fatal diagnostic outside a checkout despite a successful build. The later implementation suppresses that optional diagnostic and the smoke test rejects its recurrence. v03 passed before the driver itself was added to the artifact receipt; both earlier directories remain unchanged.
