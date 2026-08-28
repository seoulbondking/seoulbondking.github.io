@echo off
setlocal
REM ---------------------------------------------------------------
REM  Macrobox data update (run locally; domestic IP for KOSIS/BOK/FREESIS/SEIBro)
REM  Registered in Task Scheduler to run at 09:00 and 16:00.
REM  Uses "python" and "node" from PATH (same as your cmd session).
REM
REM  fetch.py output goes to the console so you can watch it live.
REM  Status lines (start / fetch result / push result) also go to
REM  tools\update.log - check there first when Pages data looks stale.
REM ---------------------------------------------------------------
set PROJ=C:\Users\infomax\Desktop\Python\macro-dashboard
set LOG=%PROJ%\tools\update.log
cd /d "%PROJ%" || exit /b 1

REM  Python picks cp949 whenever stdout is not a console, and cp949 has
REM  no em-dash. Redirecting output then killed fetch.py mid-run
REM  (2026-08-28). Pin UTF-8 so it never matters again.
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
REM  Never sit at an invisible credential prompt - fail fast instead.
set GIT_TERMINAL_PROMPT=0

echo ================================================================>>"%LOG%"
call :say "update start"

REM --- stale index.lock guard -------------------------------------
REM  A crashed/killed git leaves .git\index.lock behind. Every later
REM  "git add" then fails, "git diff --cached" reports nothing staged,
REM  and the script would exit "no changes" forever. This happened
REM  2026-08-19 and silently blocked 8 days of pushes.
if exist ".git\index.lock" (
    tasklist /fi "imagename eq git.exe" 2>nul | find /i "git.exe" >nul
    if errorlevel 1 (
        call :say "WARNING: stale .git\index.lock - removing"
        del /f /q ".git\index.lock"
    ) else (
        call :say "ERROR: git.exe is running and holds index.lock - aborting"
        goto :fail
    )
)

REM --- get any remote changes first -------------------------------
git pull --no-rebase --no-edit
if errorlevel 1 call :say "WARNING: git pull failed - continuing with local state"

REM --- fetch all indicators ---------------------------------------
echo.
echo ---- fetch ----
python fetch.py
set FETCH_RC=%errorlevel%
echo ---- fetch end ----
echo.
if not "%FETCH_RC%"=="0" (
    call :say "WARNING: fetch.py exited %FETCH_RC% - some indicators may be missing"
) else (
    call :say "fetch ok"
)

REM --- commit + push only when data actually changed ---------------
git add docs/data
if errorlevel 1 (
    call :say "ERROR: git add failed - nothing will be pushed"
    goto :fail
)

git diff --cached --quiet
if errorlevel 1 (
    git commit -m "data: auto update %date% %time%"
    if errorlevel 1 (
        call :say "ERROR: git commit failed"
        goto :fail
    )
    git push
    if errorlevel 1 (
        call :say "ERROR: git push failed - commit is local only"
        goto :fail
    )
    call :say "pushed"
) else (
    call :say "no changes"
)

call :say "update done"
exit /b 0

:fail
call :say "update FAILED"
exit /b 1

REM  echo to the screen and append the same line to the log
:say
echo [%date% %time%] %~1
echo [%date% %time%] %~1>>"%LOG%"
exit /b 0
