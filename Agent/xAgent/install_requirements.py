# -*- coding: utf-8 -*-
"""一键安装 xAgent 所需依赖 + unifypy 打包工具。

用法:
    python install_requirements.py

脚本会检测每个包是否已安装,缺什么装什么,已存在的跳过。
"""
from __future__ import annotations

import importlib.metadata
import subprocess
import sys


# xAgent 运行时依赖
RUNTIME_DEPS: list[str] = [
    "requests",          # web_tools.py: searchWeb / fetchWeb
    "trafilatura",        # web_tools.py: fetchWeb 提取正文
    "textual",            # tui/app.py: Textual TUI 界面
]

# 任务(三)打包工具
BUILD_DEPS: list[str] = [
    "unifypy",            # 打包成 Windows .exe 安装包
]


def _is_installed(pkg: str) -> bool:
    """检测包是否已安装。"""
    try:
        importlib.metadata.version(pkg)
        return True
    except importlib.metadata.PackageNotFoundError:
        return False
    except Exception:
        return False


def _pip_install(pkg: str) -> tuple[bool, str]:
    """pip install 单个包。返回 (成功, 输出摘要)。"""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", pkg, "--quiet"],
            capture_output=True,
            text=True,
            timeout=180,
        )
        ok = result.returncode == 0
        msg = (result.stdout or result.stderr or "").strip()[:200]
        return ok, msg
    except subprocess.TimeoutExpired:
        return False, "[超时] pip install 超过 180 秒"
    except Exception as e:
        return False, f"[{type(e).__name__}] {e}"


def install_all():
    print("=" * 50)
    print(" xAgent 依赖安装脚本")
    print("=" * 50)
    print(f" Python: {sys.version.split()[0]}")
    print(f" 路径:   {sys.executable}")
    print()

    # ---- 运行时依赖 ----
    print("---- 运行时依赖 ----")
    runtime_ok = 0
    for pkg in RUNTIME_DEPS:
        if _is_installed(pkg):
            ver = importlib.metadata.version(pkg)
            print(f"  ✅ {pkg}  已安装 v{ver}")
            runtime_ok += 1
        else:
            print(f"  ⬇  安装 {pkg} ...", end=" ", flush=True)
            ok, msg = _pip_install(pkg)
            if ok:
                ver = importlib.metadata.version(pkg)
                print(f"✅ v{ver}")
                runtime_ok += 1
            else:
                print(f"❌ 失败: {msg[:100]}")

    print()
    print(f"  运行时: {runtime_ok}/{len(RUNTIME_DEPS)}")

    # ---- 打包依赖 ----
    print()
    print("---- 打包工具 ----")
    build_ok = 0
    for pkg in BUILD_DEPS:
        if _is_installed(pkg):
            ver = importlib.metadata.version(pkg)
            print(f"  ✅ {pkg}  已安装 v{ver}")
            build_ok += 1
        else:
            print(f"  ⬇  安装 {pkg} ...", end=" ", flush=True)
            ok, msg = _pip_install(pkg)
            if ok:
                ver = importlib.metadata.version(pkg)
                print(f"✅ v{ver}")
                build_ok += 1
            else:
                print(f"❌ 失败: {msg[:100]}")

    print()
    print(f"  打包工具: {build_ok}/{len(BUILD_DEPS)}")

    # ---- 总结 ----
    print()
    print("=" * 50)
    total_ok = runtime_ok + build_ok
    total = len(RUNTIME_DEPS) + len(BUILD_DEPS)
    if total_ok == total:
        print(f" 🎉 全部 {total} 个依赖安装完成!")
        print()
        print(" 启动 xAgent TUI:")
        print(f"    cd xAgent  &&  python -m xAgent.main")
    else:
        print(f" ⚠️  安装 {total_ok}/{total} 成功, {total - total_ok} 个失败")
        print("  失败的包可以稍后手动装: pip install <包名>")
    print("=" * 50)


if __name__ == "__main__":
    install_all()
