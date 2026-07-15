@echo off
REM ============================================================
REM SJH.com Ingestion Agent - run against a company CSV
REM
REM Usage: drag-and-drop a company CSV file onto this .bat file,
REM OR double-click it and type the filename when prompted.
REM ============================================================

call .venv\Scripts\activate.bat

set INPUT_FILE=%~1
if "%INPUT_FILE%"=="" (
    set /p INPUT_FILE="Enter the company CSV filename (e.g. sjh_companies_100.csv): "
)

for %%F in ("%INPUT_FILE%") do set BASENAME=%%~nF
set OUTPUT_FILE=jobs_%BASENAME%.csv

echo.
echo Running ingestion agent against %INPUT_FILE% ...
echo Output will be written to %OUTPUT_FILE%
echo (and %OUTPUT_FILE% with .timing.csv for the per-company timing log)
echo.

python run_ingestion.py --input "%INPUT_FILE%" --output "%OUTPUT_FILE%"

echo.
echo Done. Check the folder for %OUTPUT_FILE%
pause
