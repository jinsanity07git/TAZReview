@echo off
cd /d "%~dp0"

:: Set virtual environment name
set VENV_DIR=viztaz_venv

:: Check if Python is installed
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH.
    pause
    exit /b
)

:: Step 1: Check if the virtual environment exists
if exist "%VENV_DIR%\Scripts\activate" (
    echo Virtual environment found. Activating...
) else (
    echo Creating virtual environment...
    python -m venv "%VENV_DIR%"
    echo Installing dependencies...
    call "%VENV_DIR%\Scripts\activate"
    pip install -r requirements.txt
)

:: Step 2: Activate the virtual environment
echo Activating virtual environment...
call "%VENV_DIR%\Scripts\activate"

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
