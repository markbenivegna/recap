#!/bin/bash
# Rebuilds the "Meeting Notes.app" launcher bundle in ~/Applications.
# Run this again after moving the project folder, or if you regenerate the
# icon (assets/generate_icon.py) and want the new artwork picked up.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$HOME/Applications/Meeting Notes.app"

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

# --- Info.plist ---
cat > "$APP_DIR/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleName</key>
	<string>Meeting Notes</string>
	<key>CFBundleDisplayName</key>
	<string>Meeting Notes</string>
	<key>CFBundleIdentifier</key>
	<string>com.markbenivegna.meetingnotes</string>
	<key>CFBundleVersion</key>
	<string>1.0</string>
	<key>CFBundleShortVersionString</key>
	<string>1.0</string>
	<key>CFBundlePackageType</key>
	<string>APPL</string>
	<key>CFBundleExecutable</key>
	<string>MeetingNotes</string>
	<key>CFBundleIconFile</key>
	<string>AppIcon</string>
	<key>NSHighResolutionCapable</key>
	<true/>
	<key>NSMicrophoneUsageDescription</key>
	<string>Meeting Notes needs microphone access to record your meetings.</string>
	<key>LSMinimumSystemVersion</key>
	<string>11.0</string>
</dict>
</plist>
PLIST

# --- Launcher ---
cat > "$APP_DIR/Contents/MacOS/MeetingNotes" <<LAUNCHER
#!/bin/bash
# Launcher for the Meeting Notes app bundle. Runs the real project's
# venv + main.py so the .app just needs to stay a thin pointer to it.

PROJECT_DIR="$PROJECT_DIR"
PYTHON="\$PROJECT_DIR/venv/bin/python3"
LOG_FILE="\$PROJECT_DIR/meeting-notes.log"

if [ ! -x "\$PYTHON" ]; then
    osascript -e 'display alert "Meeting Notes" message "Setup is missing (no venv found at '"\$PROJECT_DIR"'). Run the setup steps in README.md first." as critical'
    exit 1
fi

cd "\$PROJECT_DIR" || exit 1

# Finder/LaunchServices can launch this script under Rosetta translation on
# Apple Silicon, which crashes on this venv's arm64-only wheels. `uname -m`
# can't detect that case (it reports x86_64 while translated), so force
# native arm64 unconditionally instead of trying to detect and branch.
arch -arm64 "\$PYTHON" main.py >> "\$LOG_FILE" 2>&1
STATUS=\$?

# Closing the window terminates the process via a signal (exit code 143,
# etc.) — that's normal, not a crash. Only alert when the log shows an
# actual Python traceback, so quitting the app normally stays silent.
if [ \$STATUS -ne 0 ] && tail -n 30 "\$LOG_FILE" | grep -q "Traceback"; then
    TAIL=\$(tail -n 5 "\$LOG_FILE" | tr -d '"' | tr '\n' ' ')
    osascript -e 'display alert "Meeting Notes quit unexpectedly" message "'"\$TAIL"'" as critical'
fi

exit \$STATUS
LAUNCHER
chmod +x "$APP_DIR/Contents/MacOS/MeetingNotes"

xattr -cr "$APP_DIR"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP_DIR"

echo "Built $APP_DIR"
