# Recap

Local macOS app: record or upload a meeting, transcribe it on-device with
`faster-whisper`, summarize it with the Claude API, and file the result into
Notion as a new page.

## Setup

### 0. Prerequisites

- **macOS**, Apple Silicon (arm64) — the build script embeds an arm64-only Python runtime inside the app.
- **Python 3.9+** — macOS ships one at `/usr/bin/python3`, or install one via [Homebrew](https://brew.sh) (`brew install python3`).
- **[Homebrew](https://brew.sh)**, for the one required system dependency below.
- **ffmpeg**, used to decode recorded audio before diarization:
  ```bash
  brew install ffmpeg
  ```
  Without this, transcription of anything actually recorded through the app (as opposed to certain uploaded files) will fail silently at the diarization step.

### 1. Clone and install Python dependencies

```bash
git clone https://github.com/markbenivegna/recap.git
cd recap
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

(If you're already in the project folder, skip the `git clone`/`cd`.)

### 2. Configure API keys

```bash
cp .env.example .env
```

Open `.env` in any text editor and fill in:

- **`ANTHROPIC_API_KEY`** — go to [console.anthropic.com](https://console.anthropic.com), sign in (this is a separate pay-as-you-go account from a claude.ai subscription), open **API Keys** in the left sidebar, click **Create Key**, and paste the value in. A typical meeting (transcription + summarization) costs a few cents.
- **`NOTION_API_KEY`** — go to [notion.so/my-integrations](https://www.notion.so/my-integrations), click **New integration**, give it any name (e.g. "Recap"), and create it. Copy the **Internal Integration Secret** it shows you into `.env`.
  - **Then, separately**, in Notion itself: open every page or database you want to be able to file meeting notes into, click the **`...`** menu in the top right, go to **Connections**, and connect your new integration. Repeat for each page — pages not explicitly connected this way will never show up in the app's dropdown, even though the API key itself is valid.

Everything else in `.env` (`WHISPER_MODEL_SIZE`, `VOCABULARY_HINTS`, `DIARIZATION_THRESHOLD`, `RECORDING_OUTPUT_DEVICE`) has a working default — see the comments in `.env.example`, or the [System audio](#system-audio-hearing-both-sides-of-a-call) section below if you want to capture both sides of a call.

### 3. Build the app

```bash
./scripts/build_app.sh
```

This creates **Recap.app** in `~/Applications` with a custom icon — a one-time step that takes a minute or two. Open it from Finder or Launchpad from here on; no terminal needed after this point.

### 4. First launch

- macOS will likely show an **"unidentified developer"** Gatekeeper warning, since the app isn't code-signed. Right-click (or Control-click) the app in Finder and choose **Open** once — you'll only need to do this the first time.
- Clicking **Record** for the first time triggers a normal macOS microphone-permission prompt — click **Allow**.
- The very first recording you transcribe will trigger a one-time download of the `faster-whisper` model (a few hundred MB for the default `small` size) and the speaker-diarization model (`speechbrain/spkrec-ecapa-voxceleb`, downloaded to `.cache/`) — expect that first transcription to take noticeably longer than later ones while those download. Everything after that runs fully offline.

## Run

The normal way, day to day: open **Recap** from `~/Applications` (or Launchpad) like any other app.

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
