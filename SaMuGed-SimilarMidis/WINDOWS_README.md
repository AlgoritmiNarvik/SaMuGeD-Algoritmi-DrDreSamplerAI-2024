# SaMuGed for Windows

## Simple Installation

1. Install Python 3.8 or newer from [python.org](https://www.python.org/downloads/)
   - **Important**: Check "Add Python to PATH" during installation
   
2. Download and extract this package

3. Run the automatic installer:
   - Double-click `windows_setup.bat`
   - This script will:
     - Install all required Python packages
     - Download and set up FluidSynth
     - Download soundfont files
     - Create a desktop shortcut

4. Once installation completes, you can run SaMuGed by:
   - Using the desktop shortcut, or
   - Running `python app.py` in the application directory

## Manual Installation (If Automatic Install Fails)

If the automatic installer fails, follow these steps:

1. Install Python 3.8 or newer from [python.org](https://www.python.org/downloads/)
   - Make sure to check "Add Python to PATH" during installation

2. Open Command Prompt as Administrator
   - Press Win+X and select "Windows Terminal (Admin)" or "Command Prompt (Admin)"

3. Navigate to the SaMuGed directory:
   ```
   cd path\to\SaMuGed-SimilarMidis
   ```

4. Create and activate a virtual environment (optional but recommended):
   ```
   python -m venv venv
   venv\Scripts\activate
   ```

5. Install required packages:
   ```
   pip install -r requirements_windows.txt
   ```

6. Download and install FluidSynth:
   - Download from: [FluidSynth 2.3.4](https://github.com/FluidSynth/fluidsynth/releases/download/v2.3.4/fluidsynth-2.3.4-win10-x64.zip)
   - Extract to `bin\fluidsynth-2.3.4-win10-x64` in your SaMuGed directory

7. Download soundfont file:
   - Download from: [FluidR3_GM.sf2](https://archive.org/download/FluidR3_GM/FluidR3_GM.sf2)
   - Save to `soundfonts\FluidR3_GM.sf2` in your SaMuGed directory

8. Run the application:
   ```
   python app.py
   ```

## Troubleshooting

### FluidSynth Issues

If you encounter errors related to FluidSynth:

1. **Missing DLL errors**:
   - Make sure the FluidSynth directory is in the correct location:
     - `bin\fluidsynth-2.3.4-win10-x64\bin` should contain `fluidsynth.exe` and DLL files
   - If needed, download FluidSynth manually and extract to the correct location

2. **Soundfont not found**:
   - Ensure the soundfont file is in the correct location:
     - `soundfonts\FluidR3_GM.sf2`
   - If needed, download it manually from [here](https://archive.org/download/FluidR3_GM/FluidR3_GM.sf2)

### Python Package Issues

If you see errors about missing Python packages:

1. Make sure you're using the virtual environment:
   ```
   venv\Scripts\activate
   ```

2. Try reinstalling packages manually:
   ```
   pip install -r requirements_windows.txt --force-reinstall
   ```

3. For specific package errors, install them individually:
   ```
   pip install package_name
   ```

### Performance Issues

1. If the application runs slowly, try:
   - Reducing the cache size in settings
   - Closing other applications while running SaMuGed
   - Ensuring your computer meets the minimum requirements

## Getting Help

If you encounter issues not covered in this guide:

1. Check the [GitHub repository](https://github.com/yourrepo/SaMuGed) for known issues
2. Join our [Discord community](https://discord.gg/yourserver) for support
3. Submit a bug report with:
   - Windows version
   - Python version
   - Error messages or screenshots
   - Steps to reproduce the issue 