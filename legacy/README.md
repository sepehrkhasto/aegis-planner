# Aegis Planner 2.x (reference implementation)

This folder is the Python/PyQt6 application, version 2.11.10, moved here unchanged
on the `v3` branch. It is the **reference** for the Rust rewrite: test vectors and
sample vaults in `testdata/` are produced from this code by `tools/vectors/`.

Released 2.x versions and their fixes live on `main` (later `legacy/2.x`).
This copy is removed when Aegis 3.0 ships.

Run it or its tests from this folder:

```bash
cd legacy
pip install -r requirements-dev.txt
QT_QPA_PLATFORM=offscreen python -m pytest tests -q
python run_aegis.py
```
