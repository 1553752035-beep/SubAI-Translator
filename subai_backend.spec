# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：SubAI Translator 后端 -> subai-backend.exe（onefile / CPU 版）"""
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = []
binaries = []
hiddenimports = []

# 关键 native 库：收集数据文件、二进制与子模块
_native_pkgs = [
    "faster_whisper",
    "ctranslate2",
    "onnxruntime",
    "rapidocr_onnxruntime",
    "cv2",
    "av",
    "pyclipper",
    "shapely",
    "tokenizers",
]
for pkg in _native_pkgs:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as e:  # noqa: BLE001
        print("[spec] collect_all(%s) failed: %s" % (pkg, e))

# uvicorn / fastapi / pydantic 存在大量动态导入，收集全部子模块
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("fastapi")
hiddenimports += collect_submodules("pydantic")

a = Analysis(
    ["backend_main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["torch", "torchvision", "torchaudio", "pytest", "pip", "setuptools", "tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="subai-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
