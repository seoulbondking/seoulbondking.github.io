@echo off
REM ---------------------------------------------------------------
REM  Macrobox data update (run locally; domestic IP for KOSIS/BOK/FREESIS/SEIBro)
REM  Registered in Task Scheduler to run at 09:00 and 16:00.
REM  Uses "python" and "node" from PATH (same as your cmd session).
REM ---------------------------------------------------------------
set PROJ=C:\Users\infomax\Desktop\Python\macro-dashboard
cd /d "%PROJ%" || exit /b 1
echo [%date% %time%] update start

REM get any remote changes first
git pull --no-rebase --no-edit --quiet

REM fetch all indicators
python fetch.py
echo [%date% %time%] fetch exit code: %errorlevel%

REM commit + push only when data actually changed
git add docs/data
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "data: auto update %date% %time%"
    git push
    echo [%date% %time%] pushed
) else (
    echo [%date% %time%] no changes
)

exit /b 0
