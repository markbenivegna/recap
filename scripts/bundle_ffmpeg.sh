#!/bin/bash
# Copies Homebrew's ffmpeg into a built Recap.app and rewrites its dylib
# dependencies to relative paths (via dylibbundler) so it runs standalone on
# a machine with neither Homebrew nor ffmpeg installed — same technique
# apps like HandBrake use to embed ffmpeg. Diarization is the only thing
# that needs it (decoding recorded WebM audio); core transcription never
# touches it. Run this after scripts/recap.spec has produced dist/Recap.app:
#   scripts/bundle_ffmpeg.sh dist/Recap.app
set -euo pipefail

APP_PATH="${1:?Usage: bundle_ffmpeg.sh <path-to-Recap.app>}"

if ! command -v dylibbundler >/dev/null 2>&1; then
    echo "dylibbundler not found — install with: brew install dylibbundler" >&2
    exit 1
fi

FFMPEG_PREFIX="$(brew --prefix ffmpeg 2>/dev/null || true)"
if [ -z "$FFMPEG_PREFIX" ] || [ ! -f "$FFMPEG_PREFIX/bin/ffmpeg" ]; then
    echo "ffmpeg not found via Homebrew — install with: brew install ffmpeg" >&2
    exit 1
fi

DEST_DIR="$APP_PATH/Contents/Resources/ffmpeg-bin"
rm -rf "$DEST_DIR"
mkdir -p "$DEST_DIR"
cp "$FFMPEG_PREFIX/bin/ffmpeg" "$DEST_DIR/ffmpeg"

# -od: overwrite dylib install names in-place: -b: fix the target binary's
# own references too, not just the dylibs it depends on. -p sets the
# relative-path prefix written into every rewritten install name —
# @executable_path resolves against wherever ffmpeg itself is actually run
# from (Contents/Resources/ffmpeg-bin/ffmpeg), independent of where the
# whole Recap.app is installed.
dylibbundler -od -b \
    -x "$DEST_DIR/ffmpeg" \
    -d "$DEST_DIR/libs" \
    -p "@executable_path/libs"

echo "Bundled ffmpeg into $DEST_DIR"
