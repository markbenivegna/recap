# Meeting Notes

Local macOS app: record or upload a meeting, transcribe it on-device with
`faster-whisper`, summarize it with the Claude API, and file the result into
Notion as a new page.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and fill in:

- `ANTHROPIC_API_KEY` — from [console.anthropic.com](https://console.anthropic.com) (pay-as-you-go, separate from a claude.ai subscription)
- `NOTION_API_KEY` — create an internal integration at [notion.so/my-integrations](https://www.notion.so/my-integrations), then open each Notion page/database you want the app to see and share it with that integration (`... > Connections > Connect to`)

`faster-whisper` downloads its model automatically on first run and then works offline.

Finally, build the double-clickable app:

```bash
./scripts/build_app.sh
```

This creates **Meeting Notes.app** in `~/Applications` with a custom icon. Open it from Finder or Launchpad like any other app — no terminal needed after this point.

The first launch may show an "unidentified developer" Gatekeeper warning since the app isn't code-signed; right-click the app and choose **Open** once to get past it.

## Run

The normal way, day to day: open **Meeting Notes** from `~/Applications` (or Launchpad) like any other app.

For debugging, you can also run it directly from a terminal:

```bash
source venv/bin/activate
python3 main.py          # standalone window
python3 -m backend.app   # or: plain web app at http://127.0.0.1:5151
```

If you ever move the project folder, or want to regenerate the icon, re-run `./scripts/build_app.sh` to rebuild the app bundle.

## Flow

1. Click **Record** (grants mic access) or **Upload audio** for an existing file.
2. Stop the recording — it's transcribed locally, then summarized via Claude.
3. Read the result across the **Summary**, **Notes**, and **Transcript** tabs.
4. Pick a destination from the Notion dropdown (populated live from your workspace) and click **File to Notion** to create a new page there.

## Notes

- Recordings are transcribed then deleted from disk immediately after.
- Only pages/databases explicitly shared with your Notion integration show up in the dropdown.
- `WHISPER_MODEL_SIZE` in `.env` controls the local model (`small` by default; try `medium` for better accuracy or `base` for more speed).

## System audio (hearing both sides of a call)

By default, Record only captures your microphone. To also capture whatever's
playing out of your speakers (e.g. the other person on a Zoom/Meet call):

1. Install [BlackHole](https://github.com/ExistentialAudio/BlackHole), a free virtual audio driver:
   ```bash
   brew install blackhole-2ch
   ```
2. Open **Audio MIDI Setup** (Applications → Utilities), click `+` → **Create Multi-Output Device**, and check both your normal speakers and "BlackHole 2ch".
3. Set that Multi-Output Device as your system sound output (System Settings → Sound, or the menu bar volume icon).

Once that's set up, the app automatically detects BlackHole and mixes it with
your mic when you hit Record — no extra steps in the app itself. If BlackHole
isn't installed or isn't wired up yet, it just falls back to mic-only, same
as before.
