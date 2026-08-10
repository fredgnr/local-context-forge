# -*- mode: python ; coding: utf-8 -*-
"""Reviewed PyInstaller onedir definition for the arm64 Python sidecar."""

from pathlib import Path
import os
import stat

from PyInstaller.utils.hooks import collect_data_files, copy_metadata


SPEC_DIR = Path(SPECPATH)
SOURCE_ROOT = Path(os.environ.get("LCF_PYINSTALLER_SOURCE_ROOT", ""))
raw_source_descriptor = os.environ.get("LCF_PYINSTALLER_SOURCE_FD", "")
if not raw_source_descriptor.isascii() or not raw_source_descriptor.isdecimal():
    raise RuntimeError("PyInstaller source capability is unavailable")
source_descriptor = int(raw_source_descriptor, 10)
try:
    source_held = os.fstat(source_descriptor)
    source_named = SOURCE_ROOT.lstat()
except OSError as exc:
    raise RuntimeError("PyInstaller source capability is unavailable") from exc
if (
    not SPEC_DIR.is_absolute()
    or not SOURCE_ROOT.is_absolute()
    or stat.S_ISLNK(source_named.st_mode)
    or not stat.S_ISDIR(source_held.st_mode)
    or (source_held.st_dev, source_held.st_ino)
    != (source_named.st_dev, source_named.st_ino)
):
    raise RuntimeError("PyInstaller source capability is unavailable")
if SPEC_DIR != SOURCE_ROOT / "backend" / "packaging":
    raise RuntimeError("PyInstaller spec source layout is unexpected")
BACKEND_DIR = SOURCE_ROOT / "backend"
ENTRYPOINT = SPEC_DIR / "frozen_entrypoint.py"

datas = []
for distribution in (
    "certifi",
    "dulwich",
    "fastapi",
    "h11",
    "pydantic",
    "pydantic-core",
    "starlette",
    "urllib3",
    "uvicorn",
):
    datas += copy_metadata(distribution)
datas += collect_data_files("certifi")

hidden_imports = [
    "app.cli",
    "app.factory",
    "certifi",
    "dulwich._diff_tree",
    "dulwich._objects",
    "dulwich._pack",
    "dulwich.client",
    "dulwich.config",
    "dulwich.objects",
    "dulwich.pack",
    "dulwich.repo",
    "pydantic_core",
    "uvicorn.lifespan.on",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.h11_impl",
]

analysis = Analysis(
    [str(ENTRYPOINT)],
    pathex=[str(BACKEND_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "httptools",
        "uvloop",
        "watchfiles",
        "websockets",
        "uvicorn.loops.uvloop",
        "uvicorn.protocols.http.httptools_impl",
        "uvicorn.protocols.websockets",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="lcf-service",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="arm64",
    codesign_identity=None,
    entitlements_file=None,
    contents_directory="_internal",
)

bundle = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="lcf-service",
)
