## 2026-10-22 security dependency bumps

Bumps the 16 pins in `requirements_unix.txt` that carry open Dependabot alerts (69 alerts, 1 critical and 39 high). Each pin moves to the highest first patched version that Dependabot lists, except Werkzeug, which moves to 3.1.9, the latest 3.1 patch release. Pillow moves to 13.0.0, so this file now needs Python 3.11 or newer, which matches `requires-python` in `pyproject.toml`.

Flask 3.1.3 needs blinker 1.9.0 and wheel 0.46.2 needs packaging 24.2. Packaging 24.2 conflicts with the pinned mido 1.3.2, so `blinker`, `packaging` and `mido` move too. The CI test run uses `requirements-research.lock` and `requirements-publication.lock`, so pillow moves from 12.3.0 to 13.0.0 in `requirements-research.lock` as well (Dependabot does not scan the lock files, but that pin carried the same critical advisory). Verification covers a dry run and a real install of the updated file, `pip check`, and the CI test suite (950 passed, 40 skipped).
