from __future__ import annotations

import os
import threading
import time
import webbrowser

import httpx
import uvicorn

from app.main import create_app


HOST = "127.0.0.1"
PORT = 8000


def open_browser_when_ready() -> None:
    url = f"http://{HOST}:{PORT}"
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            response = httpx.get(f"{url}/health", timeout=1.0)
            if response.status_code == 200:
                webbrowser.open(url)
                return
        except Exception:
            pass
        time.sleep(0.4)
    webbrowser.open(url)


def main() -> None:
    app = create_app()
    if os.getenv("RTG_SKIP_BROWSER") != "1":
        threading.Thread(target=open_browser_when_ready, daemon=True).start()
    uvicorn.run(app, host=HOST, port=PORT, reload=False)


if __name__ == "__main__":
    main()
