@echo off
REM Real-Windows QA: full test suite + every page rendered at 100/125/150/200 %% on the real display driver.
REM Output: qa_output\  (zip that folder and send it back)
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe ( python -m venv .venv )
call .venv\Scripts\activate.bat
python -m pip install -q -r requirements-dev.txt
if not exist qa_output mkdir qa_output
echo [1/2] Test suite (offscreen)...
set QT_QPA_PLATFORM=offscreen
python -m pytest tests -q -p no:cacheprovider > qa_output\pytest.txt 2>&1
type qa_output\pytest.txt | findstr /R /C:"passed" /C:"failed" /C:"error"
set QT_QPA_PLATFORM=
echo [2/2] Rendering all pages at 100/125/150/200 %%...
python tools\windows_qa.py
powershell -NoProfile -Command "Compress-Archive -Force -Path qa_output\* -DestinationPath qa_output.zip"
echo.
echo Done. Send qa_output.zip back.
pause
