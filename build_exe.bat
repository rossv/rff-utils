@echo off
setlocal

:: Get current date and time safely
for /f "tokens=2 delims==" %%a in ('wmic OS Get localdatetime /value') do set "dt=%%a"
set "YYYY=%dt:~0,4%" & set "MM=%dt:~4,2%" & set "DD=%dt:~6,2%"
set "HH=%dt:~8,2%" & set "Min=%dt:~10,2%" & set "Sec=%dt:~12,2%"
set "timestamp=%YYYY%%MM%%DD%_%HH%%Min%%Sec%"

:: Archive previous build if it exists
if exist "dist\RFF_Merger.exe" (
    echo Archiving previous build RFF_Merger.exe to RFF_Merger_%timestamp%.exe...
    move "dist\RFF_Merger.exe" "dist\RFF_Merger_%timestamp%.exe"
)

:: Ensure PyInstaller is installed
call .\venv\Scripts\python -m pip install pyinstaller

:: Build the executable
echo Building RFF_Merger...
:: Pyinstaller onefile with windowed no console, imports are traced via main.py
call .\venv\Scripts\pyinstaller --noconfirm --onefile --windowed --icon="assets\icon.ico" --add-data "assets\icon.ico;assets" --name "RFF_Merger" "main.py"

if exist "dist\RFF_Merger.exe" (
    echo.
    echo Build Complete! Executable is located in the dist folder.
) else (
    echo.
    echo Build Failed!
)

pause
