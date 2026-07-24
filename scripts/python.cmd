@echo off
setlocal
set "REPO_ROOT=%~dp0.."
for %%I in ("%REPO_ROOT%") do set "REPO_ROOT=%%~fI"
set "PYTHONPYCACHEPREFIX=%REPO_ROOT%\.pycache"
if not defined PLAYWRIGHT_BROWSERS_PATH set "PLAYWRIGHT_BROWSERS_PATH=%REPO_ROOT%\.tools\ms-playwright"
if exist "%REPO_ROOT%\.tools\python-packages" (
  if defined PYTHONPATH (
    set "PYTHONPATH=%REPO_ROOT%\.tools\python-packages;%PYTHONPATH%"
  ) else (
    set "PYTHONPATH=%REPO_ROOT%\.tools\python-packages"
  )
)
if not defined PYTHONIOENCODING set "PYTHONIOENCODING=utf-8"
if defined MODEL_FACTORY_PYTHON (
  "%MODEL_FACTORY_PYTHON%" %*
) else (
  python %*
)
exit /b %ERRORLEVEL%
