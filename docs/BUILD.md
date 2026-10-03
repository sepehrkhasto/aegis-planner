# Building from source

## Requirements

- Windows 10/11 (the program targets Windows; the test suite also runs headless on Linux with Qt's `offscreen` platform).
- Python 3.10 – 3.12 from [python.org](https://www.python.org/downloads/) (tick **Add python.exe to PATH**).
- For the installer: [Inno Setup 6](https://jrsoftware.org/isinfo.php). `build_windows.bat` installs it through `winget` if it is missing.

## Run without building

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run_aegis.py
```

Use `--data-dir "D:\TestData"` to keep a development vault away from your real one.

## One‑click build

Double‑click `build_windows.bat`. It creates `.venv`, installs `requirements-dev.txt`, optionally runs the tests (`set RUN_TESTS=1`), builds the application with PyInstaller, then builds the installer with Inno Setup.

Results:

| Path | Content |
|---|---|
| `dist\AegisPlanner\AegisPlanner.exe` | portable build (copy the whole folder) |
| `installer_output\AegisPlanner-Setup-<version>.exe` | installer |

## Manual build

```bat
pip install -r requirements-dev.txt
pyinstaller packaging\aegis.spec --noconfirm --clean
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\installer.iss
```

Pass `/DAppVersion=x.y.z` to `ISCC` to override the version.

## Tests

```bat
set QT_QPA_PLATFORM=offscreen
python -m pytest tests -q
```

The suite takes several minutes. Extra checks:

```bat
python tools\chaos_gui.py --seed 3 --steps 1500 --mode big
python tools\leakcheck.py
python tools\bench.py
```

`qa_windows.bat` runs the tests and renders every page at 100/125/150/200 % scaling on a real display driver; send `qa_output.zip` with a bug report about layout.

## Releasing a new version

1. Change the version in **all** of these (the test `tests/test_vault_doors_version.py` checks them):
   - `aegis_desktop/__init__.py` (`__version__`)
   - `packaging/version_info.txt` (`filevers`, `prodvers`, `FileVersion`, `ProductVersion`)
   - `packaging/installer.iss` (`AppVersion`)
   - a new entry in `aegis_desktop/ui/whatsnew.py` and in `CHANGELOG.md`
2. Run the tests.
3. Commit, then tag and push: `git tag v2.11.11 && git push origin main --tags`.
4. The `release` workflow builds the installer and publishes it, with `SHA256SUMS.txt`, on the GitHub Releases page.

## Code signing (optional)

Signing removes the SmartScreen “unknown publisher” warning once the certificate gains reputation. Set the command before running `build_windows.bat`:

```bat
set AEGIS_SIGN_CMD=signtool sign /fd sha256 /tr http://timestamp.digicert.com /td sha256 /f cert.pfx /p PASSWORD
```

The application, the installer and the uninstaller are then signed. Never commit the certificate or its password (`.gitignore` already excludes `*.pfx`).

## Repository address

The update check and the README links use `sepehrkhasto/aegis-planner`. Replace it with your own with:

```bash
python tools/set_repo.py YOUR_USERNAME            # or YOUR_USERNAME/your-repo-name
```
