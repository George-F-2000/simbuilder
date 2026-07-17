# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('assets/pipeline.ico', '.'), ('../CSV to MDF Converter/mf4-viewer-app/assets/mf4viewer.ico', '.'), ('../CSV to MDF Converter/plt-to-mf4-app/assets/plttomf4.ico', '.'), ('web', 'web'), ('cycles', 'cycles')]
binaries = []
hiddenimports = ['viewer', 'ems_builder', 'motor_gen', 'drive_cycles', 'drive_import', 'results']
tmp_ret = collect_all('tkinterdnd2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['main.py'],
    pathex=['../CSV to MDF Converter/mf4-viewer-app'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='SimBuilder',
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
    icon=['assets\\pipeline.ico'],
)
