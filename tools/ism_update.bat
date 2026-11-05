@echo off
setlocal
REM ---------------------------------------------------------------
REM  ISM update from the Infomax Excel - double-click to run.
REM
REM  1) Infomax ISM Excel (project root) to data\us_ism.csv
REM     via tools\ism_from_infomax.py --apply. It checks against
REM     investing.com whether the dates are shifted.
REM  2) python fetch.py us_ism, rebuilds docs\data\us_ism.json
REM  3) smoke test
REM  4) asks whether to push (tools\push.bat)
REM
REM  Consensus is not in the Infomax file - add it separately with
REM  tools\ism_add.py when needed.
REM
REM  NOTE: keep this file ASCII only and never put a greater-than
REM  sign in a REM line. A Korean file name plus an arrow here made
REM  cmd truncate data\us_ism.csv on every run (2026-11-05).
REM ---------------------------------------------------------------
set PROJ=C:\Users\infomax\Desktop\Python\macro-dashboard
cd /d "%PROJ%" || goto :fail
set PYTHONIOENCODING=utf-8
chcp 65001 >nul

echo ---- 1/3 Infomax Excel to us_ism.csv ----
python tools\ism_from_infomax.py --apply
if errorlevel 1 goto :fail

echo.
echo ---- 2/3 fetch us_ism ----
python fetch.py us_ism
if errorlevel 1 goto :fail

echo.
echo ---- 3/3 smoke test ----
node tools\qa\smoke.js
if errorlevel 1 goto :fail

echo.
set ANS=
set /p ANS=Push to GitHub now? (y/N)
if /i "%ANS%"=="y" call tools\push.bat "ISM: Infomax update"

echo.
echo done.
pause
exit /b 0

:fail
echo.
echo *** FAILED - see the messages above. Nothing was pushed. ***
pause
exit /b 1
