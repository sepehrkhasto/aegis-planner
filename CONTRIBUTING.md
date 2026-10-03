# Contributing

Thank you for helping! Bug reports, ideas, translations, documentation and code are all welcome.

## Before you start

- Search existing [issues](../../issues) first.
- For a larger change, open an issue to discuss it before writing code.
- Security problems: see [SECURITY.md](SECURITY.md); do not file them publicly.
- Never attach a real vault, password or recovery key.

## Development setup

```bash
git clone https://github.com/sepehrkhasto/aegis-planner.git
cd aegis-planner
python -m venv .venv
.venv\Scripts\activate            # Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
python run_aegis.py
```

## Run the tests

```bash
set QT_QPA_PLATFORM=offscreen      # Linux/macOS: export QT_QPA_PLATFORM=offscreen
python -m pytest tests -q
```

Each GUI test creates a real vault (600,000 PBKDF2 rounds), so the whole suite takes several minutes. Run a single file while developing, e.g. `python -m pytest tests/test_updates.py -q`. Every behaviour change or bug fix needs a test; a bug fix needs a test that fails without the fix.

## Code conventions

- Python 3.10+, type hints on new public functions, `from __future__ import annotations`.
- Every source file starts with `# SPDX-License-Identifier: GPL-3.0-or-later`.
- Comments explain *why*, not *what*. Keep them short, factual and in English.
- User‑visible text is Persian and lives next to the widget that shows it. The layout is right‑to‑left: paint text with the `theme.AL_R` / `AL_L` absolute alignments.
- Use the design system (`ui/tokens.py`, `ui/system.py`, `ui/theme.py`); do not hard‑code colours, sizes or fonts.
- The core (`aegis_desktop/core/`) must not import Qt, and nothing may make network requests except `core/updates.py`.
- Never log or persist passwords, keys or vault content.
- Lint before pushing: `ruff check aegis_desktop` and `python -m pyflakes aegis_desktop`.

## Pull requests

1. Fork, create a branch (`fix/calendar-drag`, `feat/…`).
2. Keep the change focused; one topic per pull request.
3. Add or update tests and, for user‑visible changes, an entry in `CHANGELOG.md` and `ui/whatsnew.py`.
4. Make sure the full test suite passes.
5. Describe what and why in the pull request; link the issue.

By contributing you agree that your contribution is licensed under GPL‑3.0‑or‑later.
