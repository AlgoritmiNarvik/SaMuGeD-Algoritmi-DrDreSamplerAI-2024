# -*- mode: python ; coding: utf-8 -*-
import os
import sys
import glob

block_cipher = None

# Add all required data files
data_files = [
    ('soundfonts/FluidR3_GM.sf2', 'soundfonts/FluidR3_GM.sf2'),
    ('datasets/Lakh_MIDI_Clean_Patterns_v1', 'datasets/Lakh_MIDI_Clean_Patterns_v1'),
    ('cache', 'cache')
]

# Additional binaries (for FluidSynth)
binaries = []

# Add FluidSynth DLLs when building on Windows or with Wine
if sys.platform.startswith('win') or os.environ.get('WINEPREFIX'):
    # Check common locations for FluidSynth DLLs
    fluidsynth_paths = [
        # For Wine installation from script
        os.path.join(os.getcwd(), 'bin', 'fluidsynth-2.3.4-win10-x64', 'bin'),
        # For manual installation or system-wide installation
        os.path.expandvars('%ProgramFiles%\\FluidSynth\\bin'),
        os.path.expandvars('%ProgramFiles(x86)%\\FluidSynth\\bin'),
        # For other common locations
        os.path.join(os.getcwd(), 'bin'),
    ]
    
    for path in fluidsynth_paths:
        if os.path.exists(path):
            dll_files = glob.glob(os.path.join(path, '*.dll'))
            for dll in dll_files:
                binaries.append((dll, '.'))
            break

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=binaries,
    datas=data_files,
    hiddenimports=['sklearn.neighbors._partition_nodes'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SaMuGed',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='SimilarPatterns-GUI-v1.1.3.png',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SaMuGed',
) 