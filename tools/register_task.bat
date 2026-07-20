@echo off
REM ---------------------------------------------------------------
REM  Register "Macrobox Daily Update" in Windows Task Scheduler
REM  Runs every day at 08:00. Just double-click this file.
REM ---------------------------------------------------------------
set TASKNAME=MacroboxDailyUpdate
set SCRIPT=C:\Users\infomax\Desktop\Python\macro-dashboard\tools\daily_update.bat

echo.
echo   Task name : %TASKNAME%
echo   Script    : %SCRIPT%
echo   Schedule  : every day 08:00
echo.

if not exist "%SCRIPT%" (
    echo [ERROR] daily_update.bat not found: %SCRIPT%
    pause
    exit /b 1
)

schtasks /create /tn "%TASKNAME%" /tr "\"%SCRIPT%\"" /sc daily /st 08:00 /f
if errorlevel 1 (
    echo.
    echo [FAILED] Try again with right-click - "Run as administrator".
) else (
    echo.
    echo [DONE] Registered. Useful commands:
    echo    check  : schtasks /query /tn "%TASKNAME%"
    echo    run now: schtasks /run   /tn "%TASKNAME%"
    echo    delete : schtasks /delete /tn "%TASKNAME%" /f
)
echo.
pause
