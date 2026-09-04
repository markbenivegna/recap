import threading

import webview

from backend.app import app

HOST = "127.0.0.1"
PORT = 5151


def run_flask():
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False)


if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    webview.create_window("Meeting Notes", f"http://{HOST}:{PORT}", width=1000, height=800, min_size=(700, 600))
    webview.start()
