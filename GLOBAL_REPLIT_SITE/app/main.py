from __future__ import annotations

import json
import mimetypes
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = BASE_DIR / "app"
STATIC_DIR = APP_DIR / "static"
UPLOAD_DIR = APP_DIR / "uploads"

DATA_DIR = BASE_DIR / "data"
HISTORY_DIR = DATA_DIR / "chat_history"
TASKS_DIR = DATA_DIR / "tasks"
PENDING_DIR = TASKS_DIR / "pending"
PROCESSING_DIR = TASKS_DIR / "processing"
DONE_DIR = TASKS_DIR / "done"
MESSAGES_FILE = HISTORY_DIR / "messages.json"

AGENT_TOKEN = os.environ.get("AGENT_TOKEN", "dev-token-change-me")

ALLOWED_IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
MAX_FILE_SIZE = 10 * 1024 * 1024

for folder in [UPLOAD_DIR, HISTORY_DIR, PENDING_DIR, PROCESSING_DIR, DONE_DIR]:
    folder.mkdir(parents=True, exist_ok=True)

if not MESSAGES_FILE.exists():
    MESSAGES_FILE.write_text("[]", encoding="utf-8")

app = FastAPI(title="Messenger Replit Site")

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def verify_agent_token(x_agent_token: str | None) -> None:
    if not AGENT_TOKEN:
        raise HTTPException(status_code=500, detail="AGENT_TOKEN is not configured on server")

    if x_agent_token != AGENT_TOKEN:
        raise HTTPException(status_code=401, detail="Bad agent token")


def read_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_messages() -> list[dict[str, Any]]:
    data = read_json(MESSAGES_FILE, [])
    return data if isinstance(data, list) else []


def save_messages(messages: list[dict[str, Any]]) -> None:
    write_json(MESSAGES_FILE, messages)


def next_message_id(messages: list[dict[str, Any]]) -> int:
    max_id = 0
    for msg in messages:
        try:
            max_id = max(max_id, int(msg.get("id", 0)))
        except Exception:
            pass
    return max_id + 1


def get_safe_image_extension(upload: UploadFile) -> str:
    content_type = (upload.content_type or "").lower()

    if content_type in ALLOWED_IMAGE_TYPES:
        return ALLOWED_IMAGE_TYPES[content_type]

    guessed = (mimetypes.guess_extension(content_type) or "").lower()
    if guessed in [".png", ".jpg", ".jpeg", ".webp", ".gif"]:
        return ".jpg" if guessed == ".jpeg" else guessed

    original = Path(upload.filename or "").suffix.lower()
    if original in [".png", ".jpg", ".jpeg", ".webp", ".gif"]:
        return ".jpg" if original == ".jpeg" else original

    raise HTTPException(status_code=400, detail="Можно загружать только изображения: png, jpg, webp, gif")


async def save_uploaded_image(upload: UploadFile) -> str:
    ext = get_safe_image_extension(upload)
    filename = f"{uuid.uuid4().hex}{ext}"
    path = UPLOAD_DIR / filename

    size = 0
    with path.open("wb") as out:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break

            size += len(chunk)
            if size > MAX_FILE_SIZE:
                out.close()
                path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Фото слишком большое. Максимум 10 МБ.")

            out.write(chunk)

    return filename


def create_task(message: dict[str, Any]) -> dict[str, Any]:
    task_id = f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    task = {
        "task_id": task_id,
        "message_id": message["id"],
        "text": message.get("text") or "",
        "image_filename": message.get("image_filename"),
        "image_url": message.get("image_url"),
        "download_url": message.get("download_url"),
        "created_at": now_iso(),
        "status": "pending",
    }
    write_json(PENDING_DIR / f"{task_id}.json", task)
    return task


def append_system_message(text: str) -> None:
    messages = load_messages()
    messages.append(
        {
            "id": next_message_id(messages),
            "role": "system",
            "text": text,
            "image_filename": None,
            "image_url": None,
            "download_url": None,
            "created_at": now_iso(),
        }
    )
    save_messages(messages)


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"ok": True, "time": now_iso()})


@app.get("/api/messages")
async def get_messages() -> JSONResponse:
    return JSONResponse({"messages": load_messages()})


@app.post("/api/messages")
async def send_message(
    text: str | None = Form(default=""),
    file: UploadFile | None = File(default=None),
) -> JSONResponse:
    clean_text = (text or "").strip()
    image_filename = None
    image_url = None
    download_url = None

    if file and file.filename:
        image_filename = await save_uploaded_image(file)
        image_url = f"/uploads/{image_filename}"
        download_url = f"/download/{image_filename}"

    if not clean_text and not image_filename:
        raise HTTPException(status_code=400, detail="Введите текст или добавьте фото.")

    messages = load_messages()

    message = {
        "id": next_message_id(messages),
        "role": "user",
        "text": clean_text,
        "image_filename": image_filename,
        "image_url": image_url,
        "download_url": download_url,
        "created_at": now_iso(),
    }

    messages.append(message)
    save_messages(messages)

    task = create_task(message)

    messages = load_messages()
    messages.append(
        {
            "id": next_message_id(messages),
            "role": "system",
            "text": f"Задача создана: {task['task_id']}. Агент на ПК должен её забрать.",
            "image_filename": None,
            "image_url": None,
            "download_url": None,
            "created_at": now_iso(),
        }
    )
    save_messages(messages)

    return JSONResponse({"ok": True, "message": message, "task": task})


@app.get("/download/{filename}")
async def download_file(filename: str) -> FileResponse:
    safe_name = Path(filename).name
    path = UPLOAD_DIR / safe_name

    if not path.exists():
        raise HTTPException(status_code=404, detail="Файл не найден")

    return FileResponse(path, filename=safe_name, media_type="application/octet-stream")


@app.post("/api/agent/tasks/next")
async def agent_next_task(x_agent_token: str | None = Header(default=None, alias="X-Agent-Token")) -> JSONResponse:
    verify_agent_token(x_agent_token)

    pending = sorted(PENDING_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)

    if not pending:
        return JSONResponse({"ok": True, "task": None})

    path = pending[0]
    task = read_json(path, None)

    if not isinstance(task, dict):
        path.unlink(missing_ok=True)
        return JSONResponse({"ok": False, "task": None, "error": "bad_task_file"})

    task["status"] = "processing"
    task["claimed_at"] = now_iso()

    processing_path = PROCESSING_DIR / path.name
    write_json(processing_path, task)
    path.unlink(missing_ok=True)

    return JSONResponse({"ok": True, "task": task})


@app.post("/api/agent/tasks/{task_id}/done")
async def agent_done_task(
    task_id: str,
    payload: dict[str, Any] | None = None,
    x_agent_token: str | None = Header(default=None, alias="X-Agent-Token"),
) -> JSONResponse:
    verify_agent_token(x_agent_token)

    safe_task_id = Path(task_id).name
    processing_path = PROCESSING_DIR / f"{safe_task_id}.json"
    done_path = DONE_DIR / f"{safe_task_id}.json"

    task = read_json(processing_path, {"task_id": safe_task_id})
    task["status"] = "done"
    task["done_at"] = now_iso()
    task["agent_result"] = payload or {}

    write_json(done_path, task)
    processing_path.unlink(missing_ok=True)

    return JSONResponse({"ok": True})


@app.post("/api/agent/tasks/{task_id}/error")
async def agent_error_task(
    task_id: str,
    payload: dict[str, Any] | None = None,
    x_agent_token: str | None = Header(default=None, alias="X-Agent-Token"),
) -> JSONResponse:
    verify_agent_token(x_agent_token)

    safe_task_id = Path(task_id).name
    processing_path = PROCESSING_DIR / f"{safe_task_id}.json"
    error_path = DONE_DIR / f"{safe_task_id}.error.json"

    task = read_json(processing_path, {"task_id": safe_task_id})
    task["status"] = "error"
    task["error_at"] = now_iso()
    task["agent_error"] = payload or {}

    write_json(error_path, task)
    processing_path.unlink(missing_ok=True)

    append_system_message(f"Ошибка агента по задаче {safe_task_id}: {(payload or {}).get('error', 'unknown')}")

    return JSONResponse({"ok": True})


@app.post("/api/agent/tasks/{task_id}/answer")
async def agent_answer_task(
    task_id: str,
    payload: dict[str, Any],
    x_agent_token: str | None = Header(default=None, alias="X-Agent-Token"),
) -> JSONResponse:
    """
    Запасной endpoint на будущее: локальный агент сможет отправить ответ обратно в общий чат.
    payload: {"text": "ответ"}
    """
    verify_agent_token(x_agent_token)

    answer_text = str(payload.get("text") or "").strip()
    if not answer_text:
        raise HTTPException(status_code=400, detail="Empty answer text")

    messages = load_messages()
    messages.append(
        {
            "id": next_message_id(messages),
            "role": "assistant",
            "text": answer_text,
            "image_filename": None,
            "image_url": None,
            "download_url": None,
            "created_at": now_iso(),
            "task_id": Path(task_id).name,
        }
    )
    save_messages(messages)

    return JSONResponse({"ok": True})
