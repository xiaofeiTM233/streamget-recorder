# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 单文件打包配置。

用法（recorder/ 目录下）：
    uv sync --group build
    uv run pyinstaller recorder.spec --noconfirm
产物：dist/StreamGetRecorder.exe（内嵌前端静态页面，FFmpeg/Node 需用户自备）
"""
from PyInstaller.utils.hooks import collect_data_files

datas = [
    # 前端静态产物（config.py 在打包模式下从 _MEIPASS/panel/out 读取）
    ("panel/out", "panel/out"),
]
# streamget 各平台 JS 签名脚本（streamget/js/*.js）
datas += collect_data_files("streamget")

hiddenimports = [
    # uvicorn 按字符串动态导入的循环/协议实现，静态分析扫不到
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="StreamGetRecorder",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # 服务端日志直接显示在控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
