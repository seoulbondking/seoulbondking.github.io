@echo off
REM ---------------------------------------------------------------
REM  Register Macrobox auto-update in Windows Task Scheduler.
REM  Two runs per day: 09:00 and 16:00. Just double-click this file.
REM ---------------------------------------------------------------
set SCRIPT=C:\Users\infomax\Desktop\Python\macro-dashboard\tools\daily_update.bat

echo.
echo   Script   : %SCRIPT%
echo   Schedule : every day 09:00 and 16:00
echo.

if not exist "%SCRIPT%" (
    echo [ERROR] daily_update.bat not found: %SCRIPT%
    pause
    exit /b 1
)

REM remove old single 08:00 task if it exists
schtasks /delete /tn "MacroboxDailyUpdate" /f >nul 2>&1

schtasks /create /tn "MacroboxUpdateAM" /tr "\"%SCRIPT%\"" /sc daily /st 09:00 /f
schtasks /create /tn "MacroboxUpdatePM" /tr "\"%SCRIPT%\"" /sc daily /st 16:00 /f

REM run as soon as possible after a missed start (PC was off at 09:00/16:00)
powershell -NoProfile -Command "foreach($t in 'MacroboxUpdateAM','MacroboxUpdatePM'){$x=Get-ScheduledTask -TaskName $t; $x.Settings.StartWhenAvailable=$true; Set-ScheduledTask -TaskName $t -Settings $x.Settings | Out-Null}" 2>nul

if errorlevel 1 (
    echo.
    echo [FAILED] Try again: right-click this file - "Run as administrator".
) else (
    echo.
    echo [DONE] Registered two tasks. Useful commands:
    echo    check  : schtasks /query /tn "MacroboxUpdateAM"
    echo    run now: schtasks /run   /tn "MacroboxUpdateAM"
    echo    delete : schtasks /delete /tn "MacroboxUpdateAM" /f
    echo             schtasks /delete /tn "MacroboxUpdatePM" /f
)
echo.
pause
