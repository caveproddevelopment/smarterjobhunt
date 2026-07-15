@echo off
REM ============================================================
REM SJH.com Ingestion Agent - one-time Windows setup
REM Double-click this file once before your first run.
REM ============================================================

echo.
echo Checking for Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo ERROR: Python was not found.
    echo Please install Python 3.11+ from https://www.python.org/downloads/
    echo IMPORTANT: On the first install screen, check the box that says
    echo "Add python.exe to PATH" - then re-run this script.
    echo.
    pause
    exit /b 1
)

echo Python found. Creating a virtual environment in .venv ...
python -m venv .venv

echo Activating virtual environment...
call .venv\Scripts\activate.bat

echo Installing Python packages (requests, playwright, gradio, pandas)...
pip install -r requirements.txt

echo Installing Playwright's Chromium browser (this is a one-time download, ~150-300MB)...
playwright install chromium

echo.
echo ============================================================
echo Setup complete! To run the agent, drag a company CSV file
echo (e.g. sjh_companies_100.csv) onto run.bat - or double-click
echo run.bat and type the filename when prompted.
echo ============================================================
echo.
pause
