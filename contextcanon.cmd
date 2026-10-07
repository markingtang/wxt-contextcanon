@echo off
REM WXT ContextCanon launcher (Windows). Sets PYTHONPATH to packages\.
setlocal
set "ROOT=%~dp0"
if "%PYTHONPATH%"=="" (
  set "PYTHONPATH=%ROOT%packages"
) else (
  set "PYTHONPATH=%ROOT%packages;%PYTHONPATH%"
)
python -m contextcanon_cli %*
endlocal & exit /b %ERRORLEVEL%
