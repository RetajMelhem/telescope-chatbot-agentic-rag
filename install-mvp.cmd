@echo off
setlocal DisableDelayedExpansion
rem Let Windows PowerShell build its own module path when called from PowerShell 7.
set "PSModulePath="
if not exist "%~dp0install-mvp.ps1" (
    echo ERROR: install-mvp.ps1 is missing. Extract the complete project ZIP first.
    exit /b 1
)
if not "%~1"=="" goto with_arguments

"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-mvp.ps1" -Version v0.1.0
set "launcherExitCode=%errorlevel%"
echo.
pause
exit /b %launcherExitCode%

:with_arguments
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-mvp.ps1" %*
exit /b %errorlevel%
