import os
import subprocess
import sys

# Define paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_DIR = os.path.join(BASE_DIR, "venv")
REQUIREMENTS_FILE = os.path.join(BASE_DIR, "requirements.txt")

# Function to run a command
def run_command(command, shell=True):
    subprocess.run(command, shell=shell, check=True)

# Create virtual environment if it doesn't exist
if not os.path.exists(VENV_DIR):
    print("Creating virtual environment...")
    run_command(f'python -m venv "{VENV_DIR}"')

# Install dependencies
pip_executable = os.path.join(VENV_DIR, "Scripts", "pip") if sys.platform == "win32" else os.path.join(VENV_DIR, "bin", "pip")
run_command(f'"{pip_executable}" install -r "{REQUIREMENTS_FILE}"')

# Run Bokeh app
bokeh_executable = os.path.join(VENV_DIR, "Scripts", "bokeh") if sys.platform == "win32" else os.path.join(VENV_DIR, "bin", "bokeh")
run_command(f'"{bokeh_executable}" serve --show "{os.path.join(BASE_DIR, "my_app.py")}"')
