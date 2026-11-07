# Build with: .\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm RobloxAFK.spec
a = Analysis(
    ['frozen_launcher.py'], pathex=[], binaries=[], datas=[], hiddenimports=[],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['PIL', 'cv2', 'numpy', 'matplotlib', 'IPython', 'pytest'],
    noarchive=False, optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [], name='RobloxAFK',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False,
    uac_admin=False, uac_uiaccess=False,
)
