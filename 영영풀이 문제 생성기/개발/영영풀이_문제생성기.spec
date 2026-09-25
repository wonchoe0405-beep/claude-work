# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['영영풀이_문제생성기.py'],
    pathex=[],
    binaries=[],
    datas=[('예제_단어장.csv', '.'), ('어휘끝_수능편_영영풀이.csv', '.'),('C:/Windows/Fonts/malgun.ttf', '.'), ('C:/Windows/Fonts/malgunbd.ttf', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'torchvision', 'scipy', 'numpy', 'pandas', 'matplotlib', 'cv2', 'sklearn'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='영영풀이_문제생성기_최종',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
