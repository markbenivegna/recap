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

## Run

As a plain web app (browser at http://127.0.0.1:5151):

```bash
source venv/bin/activate
python3 -m backend.app
```

As a standalone desktop window (no browser chrome):

```bash
source venv/bin/activate
python3 main.py
```

## Flow

1. Click **Record** (grants mic access) or **Upload audio** for an existing file.
2. Stop the recording — it's transcribed locally, then summarized via Claude.
3. Read the result across the **Summary**, **Notes**, and **Transcript** tabs.
4. Pick a destination from the Notion dropdown (populated live from your workspace) and click **File to Notion** to create a new page there.

## Notes

- Recordings are transcribed then deleted from disk immediately after.
- Only pages/databases explicitly shared with your Notion integration show up in the dropdown.
- `WHISPER_MODEL_SIZE` in `.env` controls the local model (`small` by default; try `medium` for better accuracy or `base` for more speed).
