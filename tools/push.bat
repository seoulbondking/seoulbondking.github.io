@echo off
setlocal
REM ---------------------------------------------------------------
REM  Macrobox code push - commit and push source changes by hand.
REM
REM  daily_update.bat stages only docs\data, so dashboard code
REM  (docs\index.html, fetchers\*.py, indicators.yaml, tools\*)
REM  never goes out with it. Use this after editing code.
REM
REM  Usage:
REM      tools\push.bat                       -> "code: update"
REM      tools\push.bat "자금흐름 계절성 탭 추가"
REM ---------------------------------------------------------------
set PROJ=C:\Users\infomax\Desktop\Python\macro-dashboard
set LOG=%PROJ%\tools\update.log
cd /d "%PROJ%" || exit /b 1

REM  Never sit at an invisible credential prompt - fail fast instead.
set GIT_TERMINAL_PROMPT=0

set MSG=%~1
if "%MSG%"=="" set MSG=code: update

echo ================================================================>>"%LOG%"
call :say "push start - %MSG%"

REM --- stale lock guard -------------------------------------------
REM  A killed git leaves *.lock behind and every later command fails
REM  silently. daily_update.bat only checked index.lock, but git also
REM  writes HEAD.lock and refs\heads\<branch>.lock - an interrupted
REM  "git reset" left all three behind (2026-09-03). Check them all.
set LOCKS=
if exist ".git\index.lock" set LOCKS=1
if exist ".git\HEAD.lock" set LOCKS=1
if exist ".git\refs\heads\main.lock" set LOCKS=1
if defined LOCKS (
    tasklist /fi "imagename eq git.exe" 2>nul | find /i "git.exe" >nul
    if errorlevel 1 (
        call :say "WARNING: stale git lock files - removing"
        del /f /q ".git\index.lock" 2>nul
        del /f /q ".git\HEAD.lock" 2>nul
        del /f /q ".git\refs\heads\main.lock" 2>nul
    ) else (
        call :say "ERROR: git.exe is running and holds a lock - aborting"
        goto :fail
    )
)

REM --- get any remote changes first -------------------------------
REM  The scheduled data job pushes from the same repo, so the remote
REM  is usually ahead. Pull before staging or the push is rejected.
git pull --no-rebase --no-edit
if errorlevel 1 (
    call :say "ERROR: git pull failed - resolve it first, nothing pushed"
    goto :fail
)

git add -A
if errorlevel 1 (
    call :say "ERROR: git add failed - nothing will be pushed"
    goto :fail
)

echo.
echo ---- staged ----
git diff --cached --stat
echo ----------------
echo.

git diff --cached --quiet
if errorlevel 1 (
    git commit -m "%MSG%"
    if errorlevel 1 (
        call :say "ERROR: git commit failed"
        goto :fail
    )
    git push
    if errorlevel 1 (
        call :say "ERROR: git push failed - commit is local only"
        goto :fail
    )
    call :say "pushed - %MSG%"
) else (
    call :say "no changes"
)

exit /b 0

:fail
call :say "push FAILED"
exit /b 1

REM  echo to the screen and append the same line to the log
:say
echo [%date% %time%] %~1
echo [%date% %time%] %~1>>"%LOG%"
exit /b 0
