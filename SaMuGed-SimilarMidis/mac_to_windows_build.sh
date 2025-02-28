#!/bin/bash
# Script to build a Windows executable from macOS using Wine

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Define Wine paths
WINE_PATH="/Applications/Wine Stable.app/Contents/Resources/wine/bin/wine"
WINEBOOT_PATH="/Applications/Wine Stable.app/Contents/Resources/wine/bin/wineboot"

echo -e "${GREEN}SaMuGed Windows Build Script${NC}"
echo "This script will build a Windows executable using Wine on macOS"
echo "-----------------------------------------------------------"

# Ensure we're in the right directory (the directory containing this script)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
echo -e "${GREEN}Working directory: $(pwd)${NC}"

# Install Homebrew if not already installed
if ! command -v brew &> /dev/null; then
    echo -e "${YELLOW}Installing Homebrew...${NC}"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
else
    echo -e "${GREEN}Homebrew already installed.${NC}"
fi

# Install Wine and supporting tools
echo -e "${YELLOW}Installing Wine and XQuartz...${NC}"
brew install --cask xquartz wine-stable

# Create Wine Python environment
echo -e "${YELLOW}Setting up Wine Python environment...${NC}"

# Set Wine environment
export WINEARCH=win64
export WINEPREFIX=~/.wine64_python

# Create Wine prefix if it doesn't exist
if [ ! -d "$WINEPREFIX" ]; then
    echo -e "${YELLOW}Creating new Wine prefix at $WINEPREFIX${NC}"
    "$WINEBOOT_PATH" -u
else
    echo -e "${GREEN}Using existing Wine prefix at $WINEPREFIX${NC}"
fi

# Download and install Python for Windows
PYTHON_URL="https://www.python.org/ftp/python/3.8.10/python-3.8.10-amd64.exe"
PYTHON_INSTALLER="python-3.8.10-amd64.exe"

if [ ! -f "$PYTHON_INSTALLER" ]; then
    echo -e "${YELLOW}Downloading Windows Python installer...${NC}"
    curl -L $PYTHON_URL -o $PYTHON_INSTALLER
fi

# Wait a moment to ensure system stability
sleep 3

echo -e "${YELLOW}Installing Python for Windows in Wine...${NC}"
"$WINE_PATH" "$PYTHON_INSTALLER" /quiet InstallAllUsers=1 PrependPath=1 Include_test=0

# Wait for installation to complete
sleep 15

echo -e "${YELLOW}Updating pip and installing required packages...${NC}"
"$WINE_PATH" pip install --upgrade pip

# Install required packages
echo -e "${YELLOW}Installing Python dependencies in Wine environment...${NC}"
"$WINE_PATH" pip install -r requirements_windows.txt

# Create Windows executable
echo -e "${YELLOW}Building Windows executable with PyInstaller...${NC}"
"$WINE_PATH" pyinstaller --clean samugui.spec

echo -e "${GREEN}Build complete!${NC}"
echo "The Windows executable should be located in dist/SaMuGed/"
echo "-----------------------------------------------------------"
echo -e "${YELLOW}Creating ZIP package for distribution...${NC}"
if [ -d "dist" ]; then
  cd dist
  zip -r SaMuGed-Windows.zip SaMuGed
  cd ..
  echo -e "${GREEN}Package created: dist/SaMuGed-Windows.zip${NC}"
else
  echo -e "${RED}Error: dist directory not found. Build may have failed.${NC}"
fi
echo "This file can be sent to Windows users for installation." 