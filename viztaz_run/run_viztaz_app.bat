@echo off
cd /d "%~dp0"

:: Set Conda environment name
set CONDA_ENV=viztaz_env

:: Check if Conda is installed
where conda >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Conda is not installed or not in PATH.
    pause
    exit /b
)

:: Step 1: Check if Conda environment exists
call conda env list | findstr /C:"%CONDA_ENV%" >nul
if %errorlevel% neq 0 (
    echo Conda environment "%CONDA_ENV%" not found.
    echo Creating new Conda environment...
    call conda create --name "%CONDA_ENV%" python=3.10 -y
    echo Installing dependencies...
    call conda activate "%CONDA_ENV%"
    pip install -r requirements.txt
) else (
    echo Conda environment "%CONDA_ENV%" found.
)

:: Step 2: Activate the Conda environment
echo Activating Conda environment...
call conda activate "%CONDA_ENV%"

:: Step 3: Check if viztaz_app.py exists before launching Bokeh
if not exist "viztaz_app.py" (
    echo [ERROR] viztaz_app.py not found! Please ensure it is in the same folder.
    pause
    exit /b
)

:: Step 4: Run Bokeh app
echo Running Bokeh app...
bokeh serve --show viztaz_app.py

:: Keep window open even if there's an error
echo Press any key to exit...
pause
