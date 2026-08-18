# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('assets/pipeline.ico', '.'), ('../CSV to MDF Converter/mf4-viewer-app/assets/mf4viewer.ico', '.'), ('../CSV to MDF Converter/plt-to-mf4-app/assets/plttomf4.ico', '.'), ('web', 'web'), ('cycles', 'cycles'), ('dq_targets.json', '.')]
binaries = []
hiddenimports = ['viewer', 'plt_gui', 'ems_builder', 'motor_gen', 'fmu_inject', 'drive_cycles', 'drive_import', 'results', 'live_tail', 'drive_quality', 'pedal_map', 'perf_event', 'calibration', 'rl_gym_bridge']
tmp_ret = collect_all('tkinterdnd2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
# Explicitly bundle matplotlib (mpl-data fonts/backends/matplotlibrc) so the
# MF4 viewer opens on machines where PyInstaller's auto-hook under-collects -
# the "fault exception on another PC" cause. TkAgg backend included.
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
