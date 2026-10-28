# -*- mode: python ; coding: utf-8 -*-
import os
import glob

block_cipher = None

# 收集项目根目录下所有非 venv/__pycache__ 的 Python 文件
root_dir = os.path.abspath('.')
project_py = []
for dirpath, dirnames, filenames in os.walk(root_dir):
    dirnames[:] = [d for d in dirnames if d not in ('venv', '__pycache__', '.git', 'build', 'dist', 'output')]
    # 目标目录必须是相对路径（相对于打包根），不能是绝对路径
    rel_dir = os.path.relpath(dirpath, root_dir)
    if rel_dir == '.':
        rel_dir = '.'
    for f in filenames:
        if f.endswith('.py'):
            project_py.append((os.path.join(dirpath, f), rel_dir))

# === 关键：conda 环境的 Library\bin 下散落的 DLL，PyInstaller 自动扫描会漏掉 ===
# 一把梭全加进来（排除 Qt 相关，因为 excludes 里已排除 Qt 包）
conda_root = os.path.dirname(os.path.dirname(os.__file__))  # .../conda/Lib/site-packages -> .../conda
library_bin = os.path.join(conda_root, 'Library', 'bin')
extra_dll_binaries = []
if os.path.isdir(library_bin):
    for dll in glob.glob(os.path.join(library_bin, '*.dll')):
        dll_name = os.path.basename(dll).lower()
        # 跳过 Qt 家族（已在 excludes 里排除 Qt 包）
        if dll_name.startswith('qt') or dll_name.startswith('shiboken'):
            continue
        extra_dll_binaries.append((dll, '.'))


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=extra_dll_binaries,
    datas=project_py,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['runtime_hooks/hook_ffi.py'],
    excludes=['PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'tkinter', 'matplotlib', 'numpy', 'scipy', 'pandas'],
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
    name='xAgent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[r'vcruntime.*\.dll$', r'msvcp.*\.dll$', r'concrt.*\.dll$'],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
