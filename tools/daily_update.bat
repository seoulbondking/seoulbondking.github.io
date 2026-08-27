@echo off
setlocal
REM ---------------------------------------------------------------
REM  Macrobox data update (run locally; domestic IP for KOSIS/BOK/FREESIS/SEIBro)
REM  Registered in Task Scheduler to run at 09:00 and 16:00.
REM  Uses "python" and "node" from PATH (same as your cmd session).
REM
REM  All output is appended to tools\update.log - check there first when
REM  the GitHub Pages data looks stale.
REM ---------------------------------------------------------------
set PROJ=C:\Users\infomax\Desktop\Python\macro-dashboard
set LOG=%PROJ%\tools\update.log
cd /d "%PROJ%" || exit /b 1

call :run >> "%LOG%" 2>&1
exit /b %errorlevel%

:run
echo ================================================================
echo [%date% %time%] update start

REM --- stale index.lock guard -------------------------------------
REM  A crashed/killed git leaves .git\index.lock behind. Every later
REM  "git add" then fails, "git diff --cached" reports nothing staged,
REM  and the script would exit "no changes" forever. This happened
REM  2026-08-19 and silently blocked 8 days of pushes.
if exist ".git\index.lock" (
    tasklist /fi "imagename eq git.exe" 2>nul | find /i "git.exe" >nul
    if errorlevel 1 (
        echo [%date% %time%] WARNING: stale .git\index.lock found - removing
        del /f /q ".git\index.lock"
    ) else (
        echo [%date% %time%] ERROR: git.exe is running and holds index.lock - aborting
        exit /b 1
    )
)

REM --- get any remote changes first -------------------------------
git pull --no-rebase --no-edit
if errorlevel 1 echo [%date% %time%] WARNING: git pull failed - continuing with local state

REM --- fetch all indicators ---------------------------------------
python fetch.py
echo [%date% %time%] fetch exit code: %errorlevel%

REM --- commit + push only when data actually changed ---------------
git add docs/data
if errorlevel 1 (
    echo [%date% %time%] ERROR: git add failed - nothing will be pushed
    exit /b 1
)

git diff --cached --quiet
if errorlevel 1 (
    git commit -m "data: auto update %date% %time%"
    if errorlevel 1 (
        echo [%date% %time%] ERROR: git commit failed
        exit /b 1
    )
    git push
    if errorlevel 1 (
        echo [%date% %time%] ERROR: git push failed - commit is local only
        exit /b 1
    )
    echo [%date% %time%] pushed
) else (
    echo [%date% %time%] no changes
)

echo [%date% %time%] update done
exit /b 0
