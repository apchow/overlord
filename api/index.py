import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")

import gradio as gr  # noqa: E402
from fastapi import FastAPI  # noqa: E402

from app import demo  # noqa: E402

fastapi_app = FastAPI(title="Project Overlord // Financial Defense Engine")


@fastapi_app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "project-overlord"}


app = gr.mount_gradio_app(fastapi_app, demo, path="/")
