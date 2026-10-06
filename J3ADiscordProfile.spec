# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_all

datas = [
    ('templates', 'templates'),
    ('J3ADiscordProfileLogo.png', '.'),
    ('app_icon.ico', '.'),
    ('version.json', '.'),
]
binaries = []
hiddenimports = [
    'jinja2',
    'werkzeug',
    'flask',
    'pypresence',
    'PIL',
    'PIL.Image',
    'license_manager',
    'winreg',
    'urllib',
    'urllib.request',
    'urllib.parse',
    'hashlib',
]

for pkg in ['flask', 'jinja2', 'werkzeug', 'pypresence']:
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ['desktop_app.py'],
    pathex=[],
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
    name='J3ADiscordProfile',
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
    icon=['app_icon.ico'],
)
