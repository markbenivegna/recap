#!/bin/bash
# Rebuilds the "Recap.app" launcher bundle in ~/Applications.
# Run this again after moving the project folder, recreating the venv, or
# regenerating the icon (assets/generate_icon.py) and wanting new artwork.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$HOME/Applications/Recap.app"
VENV_PYTHON="$PROJECT_DIR/venv/bin/python3"

if [ ! -x "$VENV_PYTHON" ]; then
    echo "No venv found at $PROJECT_DIR/venv — run the setup steps in README.md first." >&2
    exit 1
fi

SITE_PACKAGES="$(cd "$PROJECT_DIR" && "$VENV_PYTHON" -c "import sysconfig; print(sysconfig.get_paths()['purelib'])")"

# Resolve the real framework interpreter behind the venv's python3 symlink,
# e.g. /Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9
FRAMEWORK_PYTHON_BIN="$(cd "$PROJECT_DIR" && "$VENV_PYTHON" -c "import os; print(os.path.realpath('$VENV_PYTHON'))")"
FRAMEWORK_VERSION_DIR="$(dirname "$(dirname "$FRAMEWORK_PYTHON_BIN")")"
SOURCE_BINARY="$FRAMEWORK_VERSION_DIR/Resources/Python.app/Contents/MacOS/Python"

if [ ! -f "$SOURCE_BINARY" ]; then
    echo "Could not find the framework Python binary at $SOURCE_BINARY" >&2
    exit 1
fi

rm -rf "$APP_DIR"
mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Resources"

# --- Icon ---
if [ ! -f "$PROJECT_DIR/assets/AppIcon.icns" ]; then
    ICONSET="$PROJECT_DIR/assets/icon.iconset"
    rm -rf "$ICONSET"
    mkdir -p "$ICONSET"
    SRC="$PROJECT_DIR/assets/icon.png"
    sips -z 16 16     "$SRC" --out "$ICONSET/icon_16x16.png" > /dev/null
    sips -z 32 32     "$SRC" --out "$ICONSET/icon_16x16@2x.png" > /dev/null
    sips -z 32 32     "$SRC" --out "$ICONSET/icon_32x32.png" > /dev/null
    sips -z 64 64     "$SRC" --out "$ICONSET/icon_32x32@2x.png" > /dev/null
    sips -z 128 128   "$SRC" --out "$ICONSET/icon_128x128.png" > /dev/null
    sips -z 256 256   "$SRC" --out "$ICONSET/icon_128x128@2x.png" > /dev/null
    sips -z 256 256   "$SRC" --out "$ICONSET/icon_256x256.png" > /dev/null
    sips -z 512 512   "$SRC" --out "$ICONSET/icon_256x256@2x.png" > /dev/null
    sips -z 512 512   "$SRC" --out "$ICONSET/icon_512x512.png" > /dev/null
    cp "$SRC" "$ICONSET/icon_512x512@2x.png"
    iconutil -c icns "$ICONSET" -o "$PROJECT_DIR/assets/AppIcon.icns"
    rm -rf "$ICONSET"
fi
cp "$PROJECT_DIR/assets/AppIcon.icns" "$APP_DIR/Contents/Resources/AppIcon.icns"

# Compiled Icon Composer bundle (assets/AppIcon.icon), for macOS 26+'s Liquid
# Glass icon rendering. Without this, Tahoe boxes up the plain .icns above
# ("icon jail") instead of rendering it natively. If assets/AppIcon.icon
# ever changes, regenerate assets/AppIcon.car by running `actool` against
# it (requires full Xcode — actool isn't in the Command Line Tools alone):
#   xcrun actool assets/AppIcon.icon --app-icon AppIcon --compile out \
#     --output-partial-info-plist out/partial-info.plist \
#     --minimum-deployment-target 15.0 --platform macosx --target-device mac
if [ -f "$PROJECT_DIR/assets/AppIcon.car" ]; then
    cp "$PROJECT_DIR/assets/AppIcon.car" "$APP_DIR/Contents/Resources/Assets.car"
fi

# --- Info.plist ---
cat > "$APP_DIR/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleName</key>
	<string>Recap</string>
	<key>CFBundleDisplayName</key>
	<string>Recap</string>
	<key>CFBundleIdentifier</key>
	<string>com.markbenivegna.meetingnotes</string>
	<key>CFBundleVersion</key>
	<string>1.0</string>
	<key>CFBundleShortVersionString</key>
	<string>1.0</string>
	<key>CFBundlePackageType</key>
	<string>APPL</string>
	<key>CFBundleExecutable</key>
	<string>Recap</string>
	<key>CFBundleIconFile</key>
	<string>AppIcon</string>
	<key>CFBundleIconName</key>
	<string>AppIcon</string>
	<key>NSHighResolutionCapable</key>
	<true/>
	<key>NSMicrophoneUsageDescription</key>
	<string>Recap needs microphone access to record your meetings.</string>
	<key>LSMinimumSystemVersion</key>
	<string>11.0</string>
	<key>NSHumanReadableCopyright</key>
	<string>Copyright © 2026 Mark Benivegna. All rights reserved.</string>
</dict>
</plist>
PLIST

# --- Embed a native arm64 copy of the interpreter inside our own bundle ---
# This is what lets macOS attribute the microphone permission prompt to
# "Recap" at all: TCC resolves privacy-prompt ownership from the
# actual running executable's on-disk path. Running the system's shared
# Python.app binary directly (the old approach) meant that path resolved to
# CommandLineTools' own Python.app bundle, which declares no
# NSMicrophoneUsageDescription — so macOS silently denied mic access with
# no prompt and no entry in System Settings at all. Copying (and thinning
# to arm64-only, which also permanently rules out the earlier
# Rosetta-translation bug) makes the running binary's path resolve to our
# own bundle instead, whose Info.plist above does declare it.
RUNTIME="$APP_DIR/Contents/MacOS/PythonRuntime"
cp "$SOURCE_BINARY" "$RUNTIME"
if lipo -info "$RUNTIME" 2>/dev/null | grep -q "Architectures in the fat file"; then
    lipo -thin arm64 "$RUNTIME" -output "$RUNTIME.thin"
    mv "$RUNTIME.thin" "$RUNTIME"
fi
# Re-point the runtime at the real framework's dylib (it's not bundled here).
install_name_tool -change "@executable_path/../../../../Python3" "$FRAMEWORK_VERSION_DIR/Python3" "$RUNTIME"
codesign -s - -f "$RUNTIME"
chmod +x "$RUNTIME"

# --- Launcher ---
cat > "$APP_DIR/Contents/MacOS/Recap" <<LAUNCHER
#!/bin/bash
# Launcher for the Recap app bundle. Runs the embedded interpreter
# (Contents/MacOS/PythonRuntime) against the real project's venv packages,
# so the .app stays a thin pointer to the actual project on disk.

PROJECT_DIR="$PROJECT_DIR"
RUNTIME="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)/PythonRuntime"
LOG_FILE="\$PROJECT_DIR/recap.log"

if [ ! -x "\$RUNTIME" ] || [ ! -d "\$PROJECT_DIR/venv" ]; then
    osascript -e 'display alert "Recap" message "Setup is missing (no venv found at '"\$PROJECT_DIR"'). Run the setup steps in README.md first." as critical'
    exit 1
fi

cd "\$PROJECT_DIR" || exit 1

export PYTHONHOME="$FRAMEWORK_VERSION_DIR"
export PYTHONPATH="$SITE_PACKAGES"
export PYTHONUNBUFFERED=1

"\$RUNTIME" "\$PROJECT_DIR/main.py" >> "\$LOG_FILE" 2>&1
STATUS=\$?

# Closing the window terminates the process via a signal (exit code 143,
# etc.) — that's normal, not a crash. Only alert when the log shows an
# actual Python traceback, so quitting the app normally stays silent.
if [ \$STATUS -ne 0 ] && tail -n 30 "\$LOG_FILE" | grep -q "Traceback"; then
    TAIL=\$(tail -n 5 "\$LOG_FILE" | tr -d '"' | tr '\n' ' ')
    osascript -e 'display alert "Recap quit unexpectedly" message "'"\$TAIL"'" as critical'
fi

exit \$STATUS
LAUNCHER
chmod +x "$APP_DIR/Contents/MacOS/Recap"

xattr -cr "$APP_DIR"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP_DIR"

echo "Built $APP_DIR"
