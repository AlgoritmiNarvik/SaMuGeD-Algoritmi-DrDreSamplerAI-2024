@echo off
REM SaMuGed Windows Setup Script
TITLE SaMuGed Windows Installer
COLOR 0A

ECHO ========================================================
ECHO SaMuGed Windows Installer
ECHO ========================================================
ECHO This script will:
ECHO 1. Check for Python installation
ECHO 2. Install required Python packages
ECHO 3. Install FluidSynth
ECHO 4. Set up the application
ECHO --------------------------------------------------------

REM Check for Python
python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    ECHO Python is not installed or not in PATH
    ECHO Please install Python 3.8 or newer from https://www.python.org/downloads/
    ECHO Be sure to check "Add Python to PATH" during installation
    PAUSE
    EXIT /B 1
)

ECHO [OK] Python is installed

REM Create virtual environment (optional)
ECHO Creating virtual environment in "venv" folder...
python -m venv venv
CALL venv\Scripts\activate.bat

REM Update pip
ECHO Updating pip...
python -m pip install --upgrade pip

REM Install required packages
ECHO Installing required packages...
python -m pip install -r requirements_windows.txt

REM Check if FluidSynth is already installed
IF EXIST "C:\Program Files\FluidSynth\bin\fluidsynth.exe" (
    ECHO [OK] FluidSynth is already installed
) ELSE IF EXIST "bin\fluidsynth-2.3.4-win10-x64\bin\fluidsynth.exe" (
    ECHO [OK] FluidSynth found in bin directory
) ELSE (
    ECHO FluidSynth not found, downloading and installing...
    
    REM Create bin directory if it doesn't exist
    IF NOT EXIST "bin" mkdir bin
    
    REM Download FluidSynth
    ECHO Downloading FluidSynth...
    powershell -Command "& {Invoke-WebRequest -Uri 'https://github.com/FluidSynth/fluidsynth/releases/download/v2.3.4/fluidsynth-2.3.4-win10-x64.zip' -OutFile 'bin\fluidsynth.zip'}"
    
    REM Extract FluidSynth
    ECHO Extracting FluidSynth...
    powershell -Command "& {Expand-Archive -Path 'bin\fluidsynth.zip' -DestinationPath 'bin' -Force}"
    
    ECHO [OK] FluidSynth installed in bin directory
)

REM Check for soundfont file
IF EXIST "soundfonts\FluidR3_GM.sf2" (
    ECHO [OK] Soundfont file found
) ELSE (
    ECHO Soundfont file not found, downloading...
    
    REM Create soundfonts directory if it doesn't exist
    IF NOT EXIST "soundfonts" mkdir soundfonts
    
    REM Download soundfont
    ECHO Downloading soundfont...
    powershell -Command "& {Invoke-WebRequest -Uri 'https://archive.org/download/FluidR3_GM/FluidR3_GM.sf2' -OutFile 'soundfonts\FluidR3_GM.sf2'}"
    
    ECHO [OK] Soundfont installed
)

REM Create desktop shortcut
ECHO Creating desktop shortcut...
SET SCRIPT_DIR=%~dp0
SET SHORTCUT_PATH=%USERPROFILE%\Desktop\SaMuGed.lnk

powershell -Command "& {$WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut('%SHORTCUT_PATH%'); $Shortcut.TargetPath = 'pythonw.exe'; $Shortcut.Arguments = '%SCRIPT_DIR%app.py'; $Shortcut.WorkingDirectory = '%SCRIPT_DIR%'; $Shortcut.IconLocation = '%SCRIPT_DIR%\icon.ico,0'; $Shortcut.Save();}"

ECHO ========================================================
ECHO Setup complete!
ECHO ========================================================
ECHO 
ECHO To run SaMuGed, either:
ECHO   1. Double-click the desktop shortcut
ECHO   2. Run 'python app.py' in this directory
ECHO 
ECHO If you encounter any issues, please check the documentation
ECHO or report them on GitHub.
ECHO ========================================================

PAUSE 