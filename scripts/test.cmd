@echo off
setlocal
call "%~dp0python.cmd" -m unittest %*
exit /b %ERRORLEVEL%
