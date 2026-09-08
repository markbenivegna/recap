# PyInstaller spec for a real, standalone, downloadable Recap.app — unlike
# scripts/build_app.sh (which stays for fast local dev: a thin launcher
# pointing at this machine's live venv), this actually freezes the
# interpreter, stdlib, and every dependency (~760MB, mostly PyTorch for
# diarization) into the bundle itself, so it runs on any Mac with nothing
# pre-installed. Build with:
#   venv/bin/pyinstaller scripts/recap.spec --noconfirm
# Output: dist/Recap.app

import os

from PyInstaller.utils.hooks import collect_all, collect_data_files

block_cipher = None
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(SPEC)))

# speechbrain dynamically imports modules by string name from its YAML
# hyperparameter files, and scikit-learn lazy-loads several of its compiled
# extensions — both are known to defeat PyInstaller's static import
# analysis. collect_all() pulls in everything (modules, data files, binary
# extensions) rather than guessing at a hiddenimports list by hand.
datas = []
binaries = []
hiddenimports = [
    # main.py imports these lazily inside try/except blocks (for the
    # WKWebView media-capture-permission patch and native window chrome),
    # so PyInstaller's static analysis can't see them from the entry script.
    "webview.platforms.cocoa",
    "AppKit",
    "Foundation",
    "WebKit",
    "Quartz",
    "objc",
    "PyObjCTools.AppHelper",
]
for pkg in ("sklearn", "scipy"):
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hiddenimports

# speechbrain can't go through collect_all/collect_submodules above: it has
# several truly-optional integrations (e.g. speechbrain.integrations.k2_fsa,
# gated behind the separate `k2` package we don't install) that raise a hard
# ImportError the moment PyInstaller's static walk tries to import them to
# check they exist — even though speechbrain's own lazy-import machinery is
# specifically designed to never touch them unless actually used. Worse,
# formatting that error crashes PyInstaller's own isolated collector
# subprocess outright (a real, reproduced crash, not a hypothetical). Copy
# the real .py source straight over as data instead — sidesteps the broken
# collection step entirely, and lets speechbrain's own lazy `!name:`-based
# dynamic imports (used throughout its inference pipeline) keep working
# against real files on disk, exactly like they do unfrozen today.
datas += collect_data_files(
    "speechbrain", include_py_files=True, excludes=["**/integrations/k2_fsa/**"]
)
hiddenimports += ["speechbrain", "speechbrain.inference", "speechbrain.inference.speaker"]

# faster-whisper ships its own packaged data (a silero VAD ONNX model) that
# plain import analysis doesn't pick up — only its .py code gets collected
# automatically, not the non-Python assets sitting alongside it.
datas += collect_data_files("faster_whisper")

datas += [
    (os.path.join(PROJECT_DIR, "frontend"), "frontend"),
    (os.path.join(PROJECT_DIR, "assets", "icon.png"), "assets"),
]

a = Analysis(
    [os.path.join(PROJECT_DIR, "main.py")],
    pathex=[PROJECT_DIR],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Recap",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    target_arch="arm64",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="Recap",
)

app = BUNDLE(
    coll,
    name="Recap.app",
    icon=os.path.join(PROJECT_DIR, "assets", "AppIcon.icns"),
    bundle_identifier="com.markbenivegna.meetingnotes",
    info_plist={
        "CFBundleName": "Recap",
        "CFBundleDisplayName": "Recap",
        "CFBundleShortVersionString": "1.0",
        "CFBundleVersion": "1.0",
        "NSHighResolutionCapable": True,
        "NSMicrophoneUsageDescription": "Recap needs microphone access to record your meetings.",
        "LSMinimumSystemVersion": "11.0",
        "NSHumanReadableCopyright": "Copyright © 2026 Mark Benivegna. All rights reserved.",
    },
)
