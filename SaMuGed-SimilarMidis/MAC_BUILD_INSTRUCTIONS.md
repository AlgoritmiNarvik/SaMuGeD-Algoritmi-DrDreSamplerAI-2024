# Building SaMuGed Windows Executable from macOS

This guide provides step-by-step instructions for building a Windows executable of SaMuGed from macOS using Wine. This approach allows you to create a Windows distribution package without needing a Windows PC.

## Prerequisites

- macOS 10.15 (Catalina) or newer
- Administrator access to your Mac
- At least 10GB of free disk space
- Good internet connection

## Automated Build Process

We've created a script that automates most of the build process. Here's how to use it:

1. Open Terminal
2. Navigate to the SaMuGed-SimilarMidis directory
3. Make the build script executable:
   ```bash
   chmod +x mac_to_windows_build.sh
   ```
4. Run the script:
   ```bash
   ./mac_to_windows_build.sh
   ```
5. The script will:
   - Install Homebrew (if not already installed)
   - Install Wine and XQuartz
   - Set up a Wine environment with Python
   - Install all required dependencies
   - Build the Windows executable using PyInstaller
   - Create a ZIP package ready for distribution

6. Once complete, find the Windows distribution package at:
   ```
   dist/SaMuGed-Windows.zip
   ```

## Manual Build Process

If you prefer to do things manually or if the script encounters issues, here's the step-by-step process:

### 1. Install Wine and XQuartz

```bash
brew install --cask xquartz wine-stable
```

### 2. Set Up Wine Environment

```bash
export WINEARCH=win64
export WINEPREFIX=~/.wine64_python
wineboot -u
```

### 3. Download and Install Python for Windows

```bash
curl -L https://www.python.org/ftp/python/3.8.10/python-3.8.10-amd64.exe -o python-3.8.10-amd64.exe
wine python-3.8.10-amd64.exe /quiet InstallAllUsers=1 PrependPath=1 Include_test=0
```

### 4. Install Required Packages

```bash
wine pip install --upgrade pip
wine pip install -r requirements_windows.txt
```

### 5. Build the Windows Executable

```bash
wine pyinstaller --clean samugui.spec
```

### 6. Create Distribution Package

```bash
cd dist
zip -r SaMuGed-Windows.zip SaMuGed
cd ..
```

## Troubleshooting

### Wine Installation Issues

If you encounter issues with Wine installation:
1. Make sure XQuartz is installed and has been launched at least once
2. Try using an alternative Wine distribution: `brew install --cask wine-staging`

### Python Installation Issues

If Python installation fails:
1. Try downloading the Python installer manually from python.org
2. Run the installer with Wine and follow the GUI installation process
3. Make sure to select "Add Python to PATH" during installation

### PyInstaller Issues

If PyInstaller produces errors:
1. Make sure all dependencies are correctly installed
2. Try running `wine pip install pyinstaller==6.2.0` to install PyInstaller explicitly
3. Check that the spec file is correctly configured

### FluidSynth Issues

If FluidSynth is not correctly included:
1. Make sure the FluidSynth DLLs are correctly specified in the spec file
2. You might need to manually copy FluidSynth DLLs to the dist directory after building

## Testing the Windows Executable

To test if the Windows executable works properly on macOS:
1. Extract the ZIP package
2. Run `wine dist/SaMuGed/SaMuGed.exe`

This will run the Windows executable through Wine, allowing you to verify basic functionality before distributing it to Windows users.

## Distribution

Once the build is complete and tested, you can:
1. Send the ZIP file to Windows users
2. Upload it as a release on GitHub
3. Provide it for download on your website

Windows users only need to extract the ZIP file and run SaMuGed.exe. 