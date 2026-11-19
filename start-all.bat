@echo off
setlocal EnableDelayedExpansion
title Helmet-Guard Start

set "ROOT=%~dp0"
set "CONDA_BASE=D:\1-Miniconda"
set "ENV_NAME=helmet-guard"
set "ENV_PY=D:\1-Miniconda\envs\helmet-guard\python.exe"
set "BACKEND_DIR=%ROOT%helmet-guard"
set "FRONT_DIR=%ROOT%admin-web"
set "BACKEND_PORT=8000"
set "FRONT_PORT=5173"

echo [1/5] Check conda env ...
if not exist "%ENV_PY%" goto :no_python
if not exist "%CONDA_BASE%\Scripts\activate.bat" goto :no_conda
echo OK conda found.
goto :check_env

:no_python
echo FAIL: not found %ENV_PY%
echo Check Miniconda path D:\1-Miniconda and env name helmet-guard.
pause
exit /b 1

:no_conda
echo FAIL: not found %CONDA_BASE%\Scripts\activate.bat
pause
exit /b 1

:check_env
echo [2/5] Check backend .env ...
if exist "%BACKEND_DIR%\.env" goto :check_deps
if exist "%BACKEND_DIR%\.env.example" goto :copy_env
echo FAIL: no .env and no .env.example in helmet-guard.
pause
exit /b 1

:copy_env
copy /y "%BACKEND_DIR%\.env.example" "%BACKEND_DIR%\.env" >nul
echo Created .env from .env.example. Edit it if needed, then run again.
pause
exit /b 0

:check_deps
echo [3/5] Check backend deps ...
"%ENV_PY%" -c "import pydantic_settings, sqlalchemy, jose"
if not errorlevel 1 goto :deps_ok
echo Missing deps, installing. This takes 1-3 min on first run ...
call "%CONDA_BASE%\Scripts\activate.bat" >nul
call conda activate %ENV_NAME%
python -m pip install -U pip >nul
cd /d "%BACKEND_DIR%"
python -m pip install -e .
"%ENV_PY%" -c "import pydantic_settings, sqlalchemy, jose"
if errorlevel 1 goto :pip_fail
echo Deps installed.
goto :check_front

:pip_fail
echo FAIL: pip install -e . failed. See messages above.
pause
exit /b 1

:deps_ok
echo OK backend deps.

:check_front
echo [4/5] Check frontend deps ...
if exist "%FRONT_DIR%\node_modules" goto :front_ok
echo First run, running npm install. This takes 2-5 min ...
cd /d "%FRONT_DIR%"
call npm install
if errorlevel 1 goto :npm_fail
goto :do_start

:npm_fail
echo FAIL: npm install failed. See messages above.
pause
exit /b 1

:front_ok
echo OK frontend deps.

:do_start
echo [5/5] Start backend %BACKEND_PORT% and frontend %FRONT_PORT% ...
start "helmet-backend" cmd /k "call D:\1-Miniconda\Scripts\activate.bat && call conda activate helmet-guard && cd /d %BACKEND_DIR% && set PYTHONUTF8=1 && python -m uvicorn app.main:app --host 127.0.0.1 --port %BACKEND_PORT% --reload"
start "helmet-admin" cmd /k "cd /d %FRONT_DIR% && npm run dev -- --host 127.0.0.1 --port %FRONT_PORT%"

echo Waiting for backend ...
set "READY=0"
for /l %%i in (1,1,30) do (
  call :probe
  if "!READY!"=="1" goto :opened
  timeout /t 1 /nobreak >nul
)
goto :opened

:probe
powershell -NoProfile -Command "try { exit ((Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health -TimeoutSec 2).StatusCode -ne 200) } catch { exit 1 }"
if not errorlevel 1 set "READY=1"
exit /b 0

:opened
start "" "http://127.0.0.1:%FRONT_PORT%/"
start "" "http://127.0.0.1:%BACKEND_PORT%/docs"

echo.
echo ==================================================
echo  Done.
echo  Admin : http://127.0.0.1:%FRONT_PORT%/
echo  API   : http://127.0.0.1:%BACKEND_PORT%/docs
echo  Health: http://127.0.0.1:%BACKEND_PORT%/health
echo  To stop: close the helmet-backend and helmet-admin windows.
echo ==================================================
pause
