@echo off
setlocal
set "REPO_ROOT=%~dp0.."
for %%I in ("%REPO_ROOT%") do set "REPO_ROOT=%%~fI"
call "%~dp0python.cmd" "%REPO_ROOT%\run_local.py" %*
exit /b %ERRORLEVEL%
