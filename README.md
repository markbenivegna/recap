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

### Auto-switching to the recording device

If you don't want your Multi-Output Device as your everyday sound output
(most people don't — it complicates normal volume control), the app can
switch your system output to it automatically only while recording, and
switch back to whatever you were using right after you hit Stop:

1. Install the audio-switching CLI tool:
   ```bash
   brew install switchaudio-osx
   ```
2. Set `RECORDING_OUTPUT_DEVICE` in `.env` to the exact name of your
   Multi-Output Device (as it appears in Audio MIDI Setup / System Settings
   → Sound) — rename it there to something memorable if you want.

With that set, hitting Record switches your output to that device, and
Stop switches back to whatever was active before. If the tool isn't
installed or the device name doesn't match anything currently available,
this step is silently skipped and nothing about recording itself changes.

If your speakers are connected over Bluetooth, macOS's Multi-Output Device
handling of Bluetooth output is unreliable (a known OS-level limitation, not
something this app or BlackHole can work around) — if you get silence after
setting this up, double check System Settings → Sound (or the menu bar) has
the **Multi-Output Device** selected, not BlackHole directly (selecting
BlackHole alone sends everything to a silent virtual sink). Also note that
while a Multi-Output Device is your output, the normal volume keys/menu bar
slider often stop reliably controlling your actual speakers — use the volume
slider next to your speakers inside the Multi-Output Device panel in Audio
MIDI Setup instead.

## Speaker labels

Recordings are automatically split by speaker using a speaker-embedding
model (`speechbrain/spkrec-ecapa-voxceleb` — an openly downloadable model, no
account or sign-up needed, unlike some diarization tools). This runs locally
alongside Whisper. When summarizing, Claude will use a speaker's real name in
the summary/notes if it's clear from what's actually said in the
conversation (e.g. someone being greeted or introduced by name); otherwise it
keeps the generic label rather than guessing.

When [system audio capture](#system-audio-hearing-both-sides-of-a-call) is
active, the app records the mic and system audio as two extra, separate
reference tracks (in addition to the main mixed recording used for
transcription) so it can tell which source each moment of the transcript
came from directly, by comparing loudness, rather than relying purely on
voice similarity — which struggles when two voices happen to sound alike.
The dominant voice on the mic is labeled **"You"**; every other distinct
voice — whether an extra voice sharing the mic (e.g. an in-person guest) or
any number of voices coming through system audio — gets a normal "Speaker N"
label. Without system audio capture active, it falls back to
voice-embedding clustering alone across the whole recording, same as before.

`DIARIZATION_THRESHOLD` in `.env` controls how aggressively segments are
split into different speakers vs. merged together — see `.env.example` for
details. The embedding model downloads once (to `.cache/`) on first use.
