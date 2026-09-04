import os
import uuid
from datetime import datetime

import webview
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

load_dotenv()

from backend import audio_switch, config as app_config, markdown_export, notion_client
from backend.diarize import diarize_segments, diarize_with_source_separation, format_transcript_with_speakers
from backend.summarize import summarize_transcript
from backend.transcribe import transcribe_audio

RECORDING_OUTPUT_DEVICE = os.environ.get("RECORDING_OUTPUT_DEVICE", "")


def _meeting_title(raw_title):
    meeting_title = (raw_title or "").strip()
    formatted_date = datetime.now().strftime("%-m/%-d/%Y at %-I:%M %p")
    return f"{meeting_title} - {formatted_date}" if meeting_title else f"Meeting Notes - {formatted_date}"

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
RECORDINGS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "recordings")
ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0


@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/icon.png")
def icon():
    return send_from_directory(ASSETS_DIR, "icon.png")


@app.route("/api/transcribe", methods=["POST"])
def api_transcribe():
    if "audio" not in request.files:
        return jsonify({"error": "No audio file provided"}), 400

    audio_file = request.files["audio"]
    if audio_file.filename == "":
        return jsonify({"error": "Empty filename"}), 400

    os.makedirs(RECORDINGS_DIR, exist_ok=True)

    def _save(upload, label):
        ext = os.path.splitext(upload.filename)[1] or ".wav"
        path = os.path.join(RECORDINGS_DIR, f"{uuid.uuid4().hex}-{label}{ext}")
        upload.save(path)
        return path

    saved_path = _save(audio_file, "main")
    # Optional reference tracks (unmixed mic-only / system-audio-only,
    # recorded in parallel with the main file) — let diarization tell which
    # source a segment came from directly, instead of relying purely on
    # voice-similarity clustering, which struggles when two voices sound
    # alike (e.g. mistaking a video's narrator for the user).
    mic_path = _save(request.files["mic_audio"], "mic") if "mic_audio" in request.files else None
    system_path = _save(request.files["system_audio"], "system") if "system_audio" in request.files else None

    try:
        result = transcribe_audio(saved_path)
        try:
            if mic_path and system_path:
                diarize_with_source_separation(mic_path, system_path, result["segments"])
            else:
                diarize_segments(saved_path, result["segments"])
            result["text"] = format_transcript_with_speakers(result["segments"])
        except Exception:
            # Speaker labeling is best-effort — fall back to a plain
            # transcript rather than failing the whole request over it.
            pass
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    finally:
        for path in (saved_path, mic_path, system_path):
            if path and os.path.exists(path):
                os.remove(path)


@app.route("/api/summarize", methods=["POST"])
def api_summarize():
    data = request.get_json(silent=True) or {}
    transcript = data.get("transcript", "")

    try:
        result = summarize_transcript(transcript)
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    return jsonify(app_config.read_config())


@app.route("/api/settings", methods=["POST"])
def api_settings_post():
    data = request.get_json(silent=True) or {}
    app_config.write_config(data)
    global RECORDING_OUTPUT_DEVICE
    RECORDING_OUTPUT_DEVICE = os.environ.get("RECORDING_OUTPUT_DEVICE", "")
    return jsonify({"ok": True})


@app.route("/api/audio/prepare-recording", methods=["POST"])
def api_audio_prepare_recording():
    switched = audio_switch.prepare_for_recording(RECORDING_OUTPUT_DEVICE)
    return jsonify({"switched": switched})


@app.route("/api/audio/restore", methods=["POST"])
def api_audio_restore():
    switched = audio_switch.restore_previous_output()
    return jsonify({"switched": switched})


@app.route("/api/notion/pages", methods=["GET"])
def api_notion_pages():
    try:
        pages = notion_client.list_pages()
        return jsonify({"pages": pages})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/notion/file", methods=["POST"])
def api_notion_file():
    data = request.get_json(silent=True) or {}
    parent_id = data.get("parent_id")
    parent_type = data.get("parent_type", "page")
    summary = data.get("summary", "")
    notes = data.get("notes", "")
    transcript = data.get("transcript", "")
    title = _meeting_title(data.get("title"))

    if not parent_id:
        return jsonify({"error": "parent_id is required"}), 400

    try:
        result = notion_client.create_meeting_page(parent_id, parent_type, title, summary, notes, transcript)
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/download-markdown", methods=["POST"])
def api_download_markdown():
    data = request.get_json(silent=True) or {}
    summary = data.get("summary", "")
    notes = data.get("notes", "")
    transcript = data.get("transcript", "")
    title = _meeting_title(data.get("title"))
    suggested_name = markdown_export.safe_filename(title) + ".md"

    try:
        if webview.windows:
            # Native "Save As" dialog — lets the user pick where it goes,
            # same as any other desktop app, rather than a fixed folder.
            result = webview.windows[0].create_file_dialog(
                webview.SAVE_DIALOG,
                directory=os.path.expanduser("~/Documents"),
                save_filename=suggested_name,
            )
            if not result:
                return jsonify({"cancelled": True})
            path = result[0] if isinstance(result, (list, tuple)) else result
        else:
            # Plain web-app mode (no native window) has no save dialog
            # available — fall back to a fixed, predictable local folder.
            fallback_dir = os.path.expanduser("~/Documents/Meeting Notes")
            os.makedirs(fallback_dir, exist_ok=True)
            path = os.path.join(fallback_dir, suggested_name)

        markdown_export.write_markdown(path, title, summary, notes, transcript)
        return jsonify({"path": path})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5151, debug=os.environ.get("FLASK_DEBUG") == "1")
