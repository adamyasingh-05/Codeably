# pyinstaller.spec
#
# Freezes api/main.py + core/ into a single self-contained binary.
# Run from the repo root:
#
#   pip install pyinstaller
#   pyinstaller pyinstaller.spec
#
# Output: dist/codeably-api   (or dist/codeably-api.exe on Windows)
# Then copy that binary into desktop/ before running electron-builder.

import sys, os
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

# ── Collect hidden imports for all providers + fastapi internals ──────────────
hiddenimports = []
for pkg in [
    'anthropic', 'openai', 'groq',
    'google.generativeai', 'mistralai', 'cohere',
    'fastapi', 'uvicorn', 'starlette',
    'pydantic', 'pydantic.v1',
    'psutil', 'psycopg2',
    'anyio', 'anyio._backends._asyncio', 'anyio._backends._trio',
    'email.mime.text', 'email.mime.multipart',
    'uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto',
    'uvicorn.protocols', 'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan', 'uvicorn.lifespan.on',
]:
    try:
        hiddenimports += collect_submodules(pkg)
    except Exception:
        pass

# Collect all datas for packages that need them (templates, schemas, etc.)
datas = []
binaries = []
for pkg in ['anthropic', 'openai', 'fastapi', 'starlette', 'pydantic']:
    try:
        d, b, h = collect_all(pkg)
        datas    += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

# Include the desktop/ui folder so the API can serve it
repo_root = os.path.dirname(os.path.abspath(SPEC))
datas += [
    (os.path.join(repo_root, 'desktop', 'ui'), 'desktop/ui'),
    (os.path.join(repo_root, 'core'),           'core'),
    (os.path.join(repo_root, 'api'),            'api'),
]

a = Analysis(
    [os.path.join(repo_root, 'api', 'main.py')],
    pathex=[repo_root],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'scipy', 'PIL', 'cv2'],
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
    name='codeably-api',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,          # compress with UPX to reduce binary size
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,     # no terminal window on Windows
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(repo_root, 'desktop', 'icons', 'icon.ico') if sys.platform == 'win32' else None,
)
