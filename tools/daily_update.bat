@echo off
REM ---------------------------------------------------------------
REM  Macrobox daily data update
REM  Run on this PC (domestic IP) so KOSIS / REB APIs are reachable.
REM  Register in Task Scheduler to run every day at 08:00.
REM ---------------------------------------------------------------
set PROJ=C:\Users\infomax\Desktop\Python\macro-dashboard
set PY=C:\Users\infomax\Desktop\Python\pythonProject\.venv\Scripts\python.exe

cd /d "%PROJ%" || exit /b 1
echo [%date% %time%] fetch start

REM pull remote changes first (e.g. GitHub Actions auto-commits)
git pull --no-rebase --quiet

"%PY%" fetch.py
echo [%date% %time%] fetch.py exit code: %errorlevel%

REM commit and push only when data changed
git add docs/data
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "data: daily update %date%"
    git push
    echo [%date% %time%] pushed
) else (
    echo [%date% %time%] no changes
)

exit /b 0
