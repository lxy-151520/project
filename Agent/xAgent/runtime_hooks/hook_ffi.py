# -*- coding: utf-8 -*-
"""PyInstaller runtime hook — 预加载 ffi DLL, 避免 _ctypes 在 onefile 模式下找不到。

PyInstaller onefile 模式启动时, 所有文件被解压到 sys._MEIPASS (临时目录)。
_ctypes.CDLL('ffi') 按名称加载 DLL 时, 搜索路径可能不包含这个临时目录,
导致 OSError: Could not find module 'ffi'.

这个 hook 在 main.py 执行之前运行, 主动把 _MEIPASS 加入 DLL 搜索路径,
并尝试预加载 ffi.dll / ffi-7.dll / ffi-8.dll 让 Windows 缓存其句柄,
后续 _ctypes 再加载就会命中已加载的模块。
"""
import ctypes
import os
import sys

# 1. 把 onefile 解压目录加到 DLL 搜索路径
if hasattr(sys, '_MEIPASS'):
    os.add_dll_directory(sys._MEIPASS)
    # 某些情况下 DLL 被放到了根目录, 也要加进去
    os.add_dll_directory(os.getcwd())

# 2. 尝试预加载 ffi 系列 DLL, 让 Windows 的 DLL 加载器把它们缓存起来
#    加载顺序很重要: 版本号高的先加载, _ctypes 后续 CDLL('ffi') 时会命中
_candidates = ['ffi-8.dll', 'ffi-7.dll', 'ffi.dll']
for _name in _candidates:
    try:
        ctypes.WinDLL(_name)
        break  # 成功一个就行
    except OSError:
        continue