import os
import uuid
from datetime import datetime

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

load_dotenv()

from backend import notion_client
from backend.summarize import summarize_transcript
from backend.transcribe import transcribe_audio

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
RECORDINGS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "recordings")

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")


@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/api/transcribe", methods=["POST"])
def api_transcribe():
    if "audio" not in request.files:
        return jsonify({"error": "No audio file provided"}), 400

    audio_file = request.files["audio"]
    if audio_file.filename == "":
        return jsonify({"error": "Empty filename"}), 400

    os.makedirs(RECORDINGS_DIR, exist_ok=True)
    ext = os.path.splitext(audio_file.filename)[1] or ".wav"
    saved_path = os.path.join(RECORDINGS_DIR, f"{uuid.uuid4().hex}{ext}")
    audio_file.save(saved_path)

    try:
        result = transcribe_audio(saved_path)
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    finally:
        if os.path.exists(saved_path):
            os.remove(saved_path)


@app.route("/api/summarize", methods=["POST"])
def api_summarize():
    data = request.get_json(silent=True) or {}
    transcript = data.get("transcript", "")

    try:
        result = summarize_transcript(transcript)
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


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
    title = data.get("title") or f"Meeting Notes - {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    if not parent_id:
        return jsonify({"error": "parent_id is required"}), 400

    try:
        result = notion_client.create_meeting_page(parent_id, parent_type, title, summary, notes, transcript)
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5151, debug=os.environ.get("FLASK_DEBUG") == "1")
