# -*- mode: python ; coding: utf-8 -*-
"""HeAgent Windows exe 打包 spec（PyInstaller）。

用法:
    python -m PyInstaller --noconfirm --clean deploy/heagent.spec

产出:
    dist/heagent.exe   （one-file 单文件控制台程序）

说明:
    - console=True: heagent 是 CLI 工具（交互式聊天 / 单次执行），非 GUI 窗口程序。
    - collect_all("mcp"): MCP SDK 含动态子模块导入（stdio/http transport、类型注册），
      静态分析会漏，须整体收集（binaries+datas+hiddenimports）。
    - collect_all("textual"): GUI（textual 扩展）含动态 widget/screen 加载，整体收集。
    - openai/anthropic/httpx/pydantic 为常规静态导入，由 Analysis 自动追踪。
"""

from PyInstaller.utils.hooks import collect_all

block_cipher = None

# ── 动态导入依赖整体收集（datas/binaries/hiddenimports 三件套）──
mcp_datas, mcp_binaries, mcp_hidden = collect_all("mcp")
textual_datas, textual_binaries, textual_hidden = collect_all("textual")

a = Analysis(
    ["../src/heagent/__main__.py"],
    pathex=["../src"],
    binaries=mcp_binaries + textual_binaries,
    datas=mcp_datas + textual_datas,
    hiddenimports=mcp_hidden + textual_hidden,
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="heagent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
