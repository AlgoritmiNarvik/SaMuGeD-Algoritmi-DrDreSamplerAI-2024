@echo off
echo Installing SaMuGed - Similar MIDI Generator & Editor
echo ------------------------------------------------------

:: Check if Python is installed
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Python is not installed or not in PATH. Please install Python 3.8 or higher.
    echo You can download Python from https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Create virtual environment
echo Creating virtual environment...
python -m venv venv
call venv\Scripts\activate.bat

:: Install dependencies
echo Installing required packages...
pip install -r requirements_windows.txt

:: Install FluidSynth for Windows
echo Installing FluidSynth...
mkdir bin 2>nul
powershell -Command "& {Invoke-WebRequest -Uri 'https://github.com/FluidSynth/fluidsynth/releases/download/v2.3.4/fluidsynth-2.3.4-win10-x64.zip' -OutFile 'fluidsynth.zip'}"
powershell -Command "& {Expand-Archive -Path 'fluidsynth.zip' -DestinationPath 'bin' -Force}"
del fluidsynth.zip

:: Update PATH environment variable
set PATH=%PATH%;%CD%\bin\fluidsynth-2.3.4-win10-x64\bin

:: Build executable
echo Building executable...
pyinstaller --clean samugui.spec

:: Create desktop shortcut
echo Creating desktop shortcut...
cscript /nologo create_shortcut.vbs "%CD%"

echo ------------------------------------------------------
echo Installation complete!
echo The executable is located in the dist\SaMuGed folder
echo A shortcut has been created on your desktop
echo ------------------------------------------------------
pause 