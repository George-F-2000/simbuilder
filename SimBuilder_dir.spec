# -*- mode: python ; coding: utf-8 -*-
# ONE-DIR variant of SimBuilder.spec - used by the INSTALLER build.
# Same contents as the one-file spec, but collected into a folder so the
# installed app launches instantly (no 98 MB temp extraction per launch,
# fewer antivirus false-positives). The one-file SimBuilder.spec remains
# the portable single-exe build; keep the two specs' datas/hiddenimports
# in sync when adding modules.
# Build (used by build_installer.bat):
#   pyinstaller --clean --noconfirm --distpath build\installer_dist ^
#     --workpath "%TEMP%\simbuilder_build_work" SimBuilder_dir.spec
from PyInstaller.utils.hooks import collect_all

datas = [('assets/pipeline.ico', '.'), ('../CSV to MDF Converter/mf4-viewer-app/assets/mf4viewer.ico', '.'), ('../CSV to MDF Converter/plt-to-mf4-app/assets/plttomf4.ico', '.'), ('web', 'web'), ('cycles', 'cycles'), ('dq_targets.json', '.')]
binaries = []
hiddenimports = ['viewer', 'plt_gui', 'ems_builder', 'motor_gen', 'fmu_inject', 'drive_cycles', 'drive_import', 'results', 'live_tail', 'drive_quality', 'pedal_map', 'perf_event', 'vigrade_export', 'calibration']
tmp_ret = collect_all('tkinterdnd2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
for _pkg in ('matplotlib', 'asammdf'):
    _r = collect_all(_pkg)
    datas += _r[0]; binaries += _r[1]; hiddenimports += _r[2]
hiddenimports += ['matplotlib.backends.backend_tkagg',
                  'matplotlib.backends.backend_agg']


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
    [],
    exclude_binaries=True,
    name='SimBuilder',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\pipeline.ico'],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SimBuilder',
)
