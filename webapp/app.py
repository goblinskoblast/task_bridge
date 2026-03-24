from fastapi import FastAPI, Depends, HTTPException, Response
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, or_
from typing import List, Optional

from db.database import get_db
from db.models import Task, User, Category, Message as MessageModel, TaskFile, Comment, EmailAccount, EmailMessage, EmailAttachment, task_assignees
from pydantic import BaseModel
import os
import html
from pathlib import Path
from datetime import datetime
import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib import parse as urlparse
from urllib import request as urlrequest

app = FastAPI(title="TaskBridge API")

import logging
logger = logging.getLogger(__name__)

GOOGLE_OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
GOOGLE_REFRESH_PREFIX = "oauth_refresh:"
YANDEX_OAUTH_AUTH_URL = "https://oauth.yandex.ru/authorize"
YANDEX_OAUTH_TOKEN_URL = "https://oauth.yandex.ru/token"
YANDEX_USERINFO_URL = "https://login.yandex.ru/info"
YANDEX_REFRESH_PREFIX = "yandex_oauth_refresh:"
OAUTH_STATE_TTL_SECONDS = 900

GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
GOOGLE_OAUTH_REDIRECT_URI = os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "").strip()
YANDEX_OAUTH_CLIENT_ID = os.getenv("YANDEX_OAUTH_CLIENT_ID", "").strip()
YANDEX_OAUTH_CLIENT_SECRET = os.getenv("YANDEX_OAUTH_CLIENT_SECRET", "").strip()
YANDEX_OAUTH_REDIRECT_URI = os.getenv("YANDEX_OAUTH_REDIRECT_URI", "").strip()
OAUTH_STATE_SECRET = os.getenv("OAUTH_STATE_SECRET", os.getenv("BOT_TOKEN", ""))
DEFAULT_PRIORITY_REMINDER_HOURS = {
    "low": 6,
    "normal": 3,
    "high": 2,
    "urgent": 2,
}


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _build_oauth_state(user_id: int) -> str:
    payload = {"uid": user_id, "ts": int(time.time()), "nonce": secrets.token_urlsafe(8)}
    payload_part = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sign = hmac.new(OAUTH_STATE_SECRET.encode("utf-8"), payload_part.encode("utf-8"), hashlib.sha256).digest()
    return f"{payload_part}.{_b64url_encode(sign)}"


def _verify_oauth_state(state: str) -> int:
    if not OAUTH_STATE_SECRET:
        raise ValueError("OAUTH_STATE_SECRET is not configured")

    payload_part, sign_part = state.split(".", 1)
    expected_sign = hmac.new(OAUTH_STATE_SECRET.encode("utf-8"), payload_part.encode("utf-8"), hashlib.sha256).digest()
    provided_sign = _b64url_decode(sign_part)
    if not hmac.compare_digest(expected_sign, provided_sign):
        raise ValueError("Invalid OAuth state signature")

    payload = json.loads(_b64url_decode(payload_part).decode("utf-8"))
    created_ts = int(payload.get("ts", 0))
    if int(time.time()) - created_ts > OAUTH_STATE_TTL_SECONDS:
        raise ValueError("OAuth state expired")

    uid = int(payload.get("uid", 0))
    if uid <= 0:
        raise ValueError("Invalid OAuth state user")
    return uid


def _exchange_google_code(code: str) -> dict:
    if not GOOGLE_OAUTH_CLIENT_ID or not GOOGLE_OAUTH_CLIENT_SECRET or not GOOGLE_OAUTH_REDIRECT_URI:
        raise ValueError("Google OAuth is not configured")

    payload = urlparse.urlencode({
        "code": code,
        "client_id": GOOGLE_OAUTH_CLIENT_ID,
        "client_secret": GOOGLE_OAUTH_CLIENT_SECRET,
        "redirect_uri": GOOGLE_OAUTH_REDIRECT_URI,
        "grant_type": "authorization_code",
    }).encode("utf-8")

    req = urlrequest.Request(
        GOOGLE_OAUTH_TOKEN_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlrequest.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_google_email(access_token: str) -> str:
    req = urlrequest.Request(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        method="GET",
    )
    with urlrequest.urlopen(req, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))

    email = (payload.get("email") or "").strip().lower()
    if not email:
        raise ValueError("Google userinfo does not contain email")
    return email


def _exchange_yandex_code(code: str) -> dict:
    if not YANDEX_OAUTH_CLIENT_ID or not YANDEX_OAUTH_CLIENT_SECRET or not YANDEX_OAUTH_REDIRECT_URI:
        raise ValueError("Yandex OAuth is not configured")

    payload = urlparse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "client_id": YANDEX_OAUTH_CLIENT_ID,
        "client_secret": YANDEX_OAUTH_CLIENT_SECRET,
    }).encode("utf-8")

    req = urlrequest.Request(
        YANDEX_OAUTH_TOKEN_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlrequest.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_yandex_email(access_token: str) -> str:
    req = urlrequest.Request(
        f"{YANDEX_USERINFO_URL}?format=json",
        headers={"Authorization": f"OAuth {access_token}"},
        method="GET",
    )
    with urlrequest.urlopen(req, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))

    email = (payload.get("default_email") or payload.get("email") or "").strip().lower()
    if not email:
        raise ValueError("Yandex userinfo does not contain email")
    return email


def _oauth_result_html(ok: bool, message: str, user_id: Optional[int] = None) -> HTMLResponse:
    status = "Success" if ok else "Error"
    color = "#1a7f37" if ok else "#b42318"
    safe_message = html.escape(message)
    redirect_url = "/webapp/index.html"
    if user_id:
        redirect_url = f"/webapp/index.html?user_id={user_id}&tab=emails&oauth_status={'success' if ok else 'error'}"
    body = f"""
    <html><head><meta charset=\"utf-8\" /><title>{status}</title></head>
    <body style=\"font-family:Arial,sans-serif;padding:24px;\">
      <h2 style=\"color:{color};\">{status}</h2>
      <p>{safe_message}</p>
      <p><a href=\"{redirect_url}\">Back to dashboard</a></p>
      <script>setTimeout(function() {{ window.location.href='{redirect_url}'; }}, 1800);</script>
    </body></html>
    """
    return HTMLResponse(content=body)


def format_datetime_utc(dt):
    """
    Форматирует datetime в ISO формат с UTC timezone.
    Добавляет 'Z' в конец для обозначения UTC.
    """
    if dt is None:
        return None
    return dt.isoformat() + 'Z'


def get_default_reminder_interval_hours(priority: Optional[str]) -> int:
    return DEFAULT_PRIORITY_REMINDER_HOURS.get((priority or "normal").lower(), 3)


def serialize_task(task: Task) -> dict:
    assignees = []
    for assignee in task.assignees:
        assignees.append({
            "id": assignee.id,
            "telegram_id": assignee.telegram_id,
            "username": assignee.username,
            "first_name": assignee.first_name
        })

    creator = None
    if task.creator:
        creator = {
            "id": task.creator.id,
            "telegram_id": task.creator.telegram_id,
            "username": task.creator.username,
            "first_name": task.creator.first_name
        }

    category = None
    if task.category:
        category = {
            "id": task.category.id,
            "name": task.category.name,
            "description": task.category.description,
            "keywords": task.category.keywords
        }

    default_reminder_hours = get_default_reminder_interval_hours(task.priority)

    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "priority": task.priority,
        "due_date": format_datetime_utc(task.due_date),
        "created_at": format_datetime_utc(task.created_at),
        "updated_at": format_datetime_utc(task.updated_at),
        "assignees": assignees,
        "creator": creator,
        "category": category,
        "reminder_interval_hours": task.reminder_interval_hours,
        "default_reminder_interval_hours": default_reminder_hours,
        "effective_reminder_interval_hours": task.reminder_interval_hours or default_reminder_hours,
        "last_assignee_reminder_sent_at": format_datetime_utc(task.last_assignee_reminder_sent_at),
    }

# Определяем пути к файлам
webapp_dir = Path(__file__).parent.resolve()
dist_dir = webapp_dir / "dist"
index_html_path = dist_dir / "index.html"

logger.info(f"Current working directory: {Path.cwd()}")
logger.info(f"Webapp directory: {webapp_dir}")
logger.info(f"Dist directory: {dist_dir}")
logger.info(f"Index.html path: {index_html_path}")
logger.info(f"Index.html exists: {index_html_path.exists()}")

# Проверяем что React приложение собрано
if not dist_dir.exists() or not index_html_path.exists():
    logger.error(f"React app not built! Please run 'npm run build' in webapp/ directory")
    logger.error(f"Expected dist directory at: {dist_dir}")
    logger.error(f"Expected index.html at: {index_html_path}")
    raise RuntimeError(
        "React application not built. Please run 'cd webapp && npm install && npm run build'"
    )

# Mount static files (React assets)
assets_dir = dist_dir / "assets"
if assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")
    logger.info(f"✓ Mounted assets directory: {assets_dir}")
else:
    logger.error(f"Assets directory not found at {assets_dir}")
    raise RuntimeError(f"React assets not found at {assets_dir}")


@app.get("/", response_class=HTMLResponse)
async def read_root():
    """Главная страница - показываем index.html из dist"""
    logger.info(f"GET / - Attempting to serve index.html")
    logger.info(f"index_html_path: {index_html_path}")
    logger.info(f"index_html_path.exists(): {index_html_path.exists()}")
    logger.info(f"index_html_path.is_file(): {index_html_path.is_file() if index_html_path.exists() else 'N/A'}")

    if not index_html_path.exists():
        logger.error(f"index.html NOT FOUND at {index_html_path}")
        logger.error(f"Available files in {webapp_dir}: {list(webapp_dir.glob('*'))}")
        if dist_dir:
            logger.error(f"Available files in {dist_dir}: {list(dist_dir.glob('*')) if dist_dir.exists() else 'Directory does not exist'}")
        raise HTTPException(status_code=404, detail=f"index.html not found at {index_html_path}")

    logger.info(f"Successfully serving index.html from {index_html_path}")
    return FileResponse(str(index_html_path))


@app.get("/webapp/index.html", response_class=HTMLResponse)
async def read_webapp():
    """Отображение веб-приложения (для совместимости с WebApp кнопками)"""
    if not index_html_path.exists():
        logger.error(f"index.html NOT FOUND at {index_html_path}")
        raise HTTPException(status_code=404, detail=f"index.html not found at {index_html_path}")
    logger.info(f"Serving index.html from {index_html_path}")
    return FileResponse(str(index_html_path))


@app.get("//webapp/index.html", response_class=HTMLResponse)
async def read_webapp_double_slash():
    """Fallback для двойного слэша (если WEB_APP_DOMAIN заканчивается на /)"""
    logger.warning("Request with double slash! Check WEB_APP_DOMAIN configuration")
    if not index_html_path.exists():
        logger.error(f"index.html NOT FOUND at {index_html_path}")
        raise HTTPException(status_code=404, detail=f"index.html not found at {index_html_path}")
    logger.info(f"Serving index.html from {index_html_path}")
    return FileResponse(str(index_html_path))


@app.get("/health")
async def health_check():
    """Health check endpoint для мониторинга и пробуждения (Render.com + cron-job.org)"""
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "TaskBridge"
    }


@app.get("/api/tasks", response_model=List[dict])
async def get_tasks(
    status: Optional[str] = None,
    category_id: Optional[int] = None,
    assigned_to: Optional[int] = None,
    created_by: Optional[int] = None,
    db: Session = Depends(get_db)
):
    if not assigned_to and not created_by:
        logger.error(f"API /tasks called without assigned_to or created_by filters!")
        raise HTTPException(
            status_code=400,
            detail="Required parameter missing: either 'assigned_to' or 'created_by' must be specified"
        )

    logger.info(f"GET /api/tasks - Filters: status={status}, category_id={category_id}, assigned_to={assigned_to}, created_by={created_by}")

    query = db.query(Task)

    if status:
        query = query.filter(Task.status == status)
    if category_id:
        query = query.filter(Task.category_id == category_id)

    if assigned_to and created_by:
        query = query.outerjoin(Task.assignees).filter(
            or_(
                Task.created_by == created_by,
                User.id == assigned_to
            )
        ).distinct()
    elif created_by:
        query = query.filter(Task.created_by == created_by)
    elif assigned_to:
        query = query.join(Task.assignees).filter(User.id == assigned_to)

    tasks = query.order_by(desc(Task.created_at)).all()

    logger.info(f"Found {len(tasks)} tasks for user (assigned_to={assigned_to}, created_by={created_by})")

    result = [serialize_task(task) for task in tasks]

    for task_data in result:
        logger.info(f"  Task #{task_data['id']}: '{task_data['title']}' - created_by={task_data['creator']['id'] if task_data['creator'] else None}, assignees={[a['id'] for a in task_data['assignees']]}")

    return result


@app.get("/api/tasks/{task_id}", response_model=dict)
async def get_task(task_id: int, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return serialize_task(task)


class TaskSettingsUpdate(BaseModel):
    reminder_interval_hours: Optional[int] = None


class TaskDueDateUpdate(BaseModel):
    due_date: Optional[str] = None


@app.patch("/api/tasks/{task_id}/settings")
async def update_task_settings(
    task_id: int,
    settings: TaskSettingsUpdate,
    db: Session = Depends(get_db)
):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if settings.reminder_interval_hours is None:
        task.reminder_interval_hours = None
    else:
        if settings.reminder_interval_hours <= 0:
            raise HTTPException(status_code=400, detail="Reminder interval must be positive")
        task.reminder_interval_hours = settings.reminder_interval_hours

    db.commit()
    db.refresh(task)
    return serialize_task(task)


@app.patch("/api/tasks/{task_id}/due-date")
async def update_task_due_date(
    task_id: int,
    payload: TaskDueDateUpdate,
    db: Session = Depends(get_db)
):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if payload.due_date:
        try:
            task.due_date = datetime.fromisoformat(payload.due_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid due_date format")
    else:
        task.due_date = None

    db.commit()
    db.refresh(task)
    return serialize_task(task)


@app.patch("/api/tasks/{task_id}/status")
async def update_task_status(
    task_id: int,
    status: str,
    user_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """Обновить статус задачи"""
    task = db.query(Task).filter(Task.id == task_id).first()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if status not in ["pending", "in_progress", "completed", "cancelled"]:
        raise HTTPException(status_code=400, detail="Invalid status")

    # Сохраняем старый статус для уведомления
    old_status = task.status

    # Обновляем статус
    task.status = status
    db.commit()

    # Отправляем уведомления если статус действительно изменился и известен user_id
    if old_status != status and user_id:
        try:
            from bot.notifications import notify_status_changed
            import asyncio
            asyncio.create_task(
                notify_status_changed(
                    task_id=task_id,
                    old_status=old_status,
                    new_status=status,
                    changed_by_user_id=user_id,
                    db=db
                )
            )
        except Exception as e:
            logger.error(f"Failed to send status change notifications: {e}")
            # Не прерываем выполнение, уведомление не критично

    return {"id": task.id, "status": task.status}


@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: int, db: Session = Depends(get_db)):
    """Удалить задачу"""
    task = db.query(Task).filter(Task.id == task_id).first()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    db.delete(task)
    db.commit()

    return {"message": "Task deleted successfully"}


@app.get("/api/categories", response_model=List[dict])
async def get_categories(db: Session = Depends(get_db)):
    """Получить список категорий"""
    categories = db.query(Category).all()
    
    result = []
    for category in categories:
        task_count = db.query(func.count(Task.id)).filter(Task.category_id == category.id).scalar()
        result.append({
            "id": category.id,
            "name": category.name,
            "description": category.description,
            "keywords": category.keywords,
            "task_count": task_count
        })
    
    return result


@app.get("/api/users", response_model=List[dict])
async def get_users(current_user_id: Optional[int] = None, db: Session = Depends(get_db)):
    """
    Получить список пользователей

    SECURITY: Если указан current_user_id, возвращает только пользователей из общих чатов.
    Это предотвращает утечку данных о пользователях из других чатов.
    """

    # SECURITY FIX: Фильтруем пользователей по общим чатам
    if current_user_id:
        # Шаг 1: Находим все chat_id где есть сообщения от текущего пользователя
        current_user_chats = db.query(MessageModel.chat_id).filter(
            MessageModel.user_id == current_user_id
        ).distinct().subquery()

        # Шаг 2: Находим всех пользователей, которые писали в этих чатах
        users_in_common_chats = db.query(MessageModel.user_id).filter(
            MessageModel.chat_id.in_(current_user_chats),
            MessageModel.user_id.isnot(None)
        ).distinct().subquery()

        # Шаг 3: Получаем User объекты только для этих пользователей
        users = db.query(User).filter(
            User.id.in_(users_in_common_chats),
            User.is_bot == False
        ).all()

        logger.info(f"Filtered users for user_id={current_user_id}: {len(users)} users from common chats")
    else:
        # Если не указан current_user_id - возвращаем всех (для обратной совместимости)
        # НО это небезопасно! Рекомендуется всегда передавать current_user_id
        logger.warning("GET /api/users called without current_user_id - returning all users (INSECURE)")
        users = db.query(User).filter(User.is_bot == False).all()

    result = []
    for user in users:
        # Подсчитываем задачи через many-to-many связь
        task_count = db.query(func.count(Task.id)).join(
            task_assignees
        ).filter(
            task_assignees.c.user_id == user.id
        ).scalar()

        result.append({
            "id": user.id,
            "telegram_id": user.telegram_id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "task_count": task_count
        })

    return result


@app.get("/api/stats", response_model=dict)
async def get_stats(
    created_by: Optional[int] = None,
    assigned_to: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """
    Получить статистику задач

    Параметры:
    - created_by: ID создателя (для вкладки "Назначенные мной")
    - assigned_to: ID исполнителя (для вкладки "Мои задачи")
    """
    query = db.query(Task)

    # Фильтруем по создателю или исполнителю
    if created_by:
        query = query.filter(Task.created_by == created_by)
    elif assigned_to:
        query = query.join(Task.assignees).filter(User.id == assigned_to)

    total_tasks = query.count()
    pending_tasks = query.filter(Task.status == "pending").count()
    in_progress_tasks = query.filter(Task.status == "in_progress").count()
    completed_tasks = query.filter(Task.status == "completed").count()
    total_users = db.query(func.count(User.id)).filter(User.is_bot == False).scalar()

    return {
        "total_tasks": total_tasks,
        "pending_tasks": pending_tasks,
        "in_progress_tasks": in_progress_tasks,
        "completed_tasks": completed_tasks,
        "total_users": total_users
    }


# Файлы задач
@app.get("/api/tasks/{task_id}/files", response_model=List[dict])
async def get_task_files(task_id: int, db: Session = Depends(get_db)):
    """Получить список файлов задачи"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    files = db.query(TaskFile).filter(TaskFile.task_id == task_id).order_by(desc(TaskFile.created_at)).all()

    result = []
    for file in files:
        uploader = db.query(User).filter(User.id == file.uploaded_by_id).first()
        result.append({
            "id": file.id,
            "file_type": file.file_type,
            "file_id": file.file_id,
            "file_name": file.file_name,
            "file_size": file.file_size,
            "mime_type": file.mime_type,
            "caption": file.caption,
            "created_at": format_datetime_utc(file.created_at),
            "uploaded_by": {
                "id": uploader.id,
                "username": uploader.username,
                "first_name": uploader.first_name
            } if uploader else None
        })

    return result



class CommentCreate(BaseModel):
    text: str
    user_id: int


class AssigneeUpdate(BaseModel):
    user_id: int


@app.get("/api/tasks/{task_id}/comments", response_model=List[dict])
async def get_task_comments(task_id: int, db: Session = Depends(get_db)):
    """Получить список комментариев задачи"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    comments = db.query(Comment).filter(Comment.task_id == task_id).order_by(Comment.created_at).all()

    result = []
    for comment in comments:
        author = db.query(User).filter(User.id == comment.user_id).first()
        result.append({
            "id": comment.id,
            "text": comment.text,
            "created_at": format_datetime_utc(comment.created_at),
            "author": {
                "id": author.id,
                "username": author.username,
                "first_name": author.first_name
            } if author else None
        })

    return result


@app.post("/api/tasks/{task_id}/comments", response_model=dict)
async def create_task_comment(task_id: int, comment_data: CommentCreate, db: Session = Depends(get_db)):
    """Создать комментарий к задаче"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    user = db.query(User).filter(User.id == comment_data.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    comment = Comment(
        task_id=task_id,
        user_id=comment_data.user_id,
        text=comment_data.text
    )

    db.add(comment)
    db.commit()
    db.refresh(comment)

    # Отправляем уведомления о новом комментарии
    try:
        from bot.notifications import notify_comment_added
        import asyncio

        # Запускаем отправку уведомлений в фоне
        asyncio.create_task(notify_comment_added(task_id, comment_data.user_id, comment_data.text, db))
    except Exception as e:
        logger.error(f"Failed to send comment notifications: {e}")
        # Не падаем, если уведомления не отправились

    return {
        "id": comment.id,
        "text": comment.text,
        "created_at": format_datetime_utc(comment.created_at),
        "author": {
            "id": user.id,
            "username": user.username,
            "first_name": user.first_name
        }
    }


@app.post("/api/tasks/{task_id}/assignees")
async def add_task_assignee(task_id: int, assignee_data: AssigneeUpdate, db: Session = Depends(get_db)):
    """Добавить исполнителя к задаче"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    user = db.query(User).filter(User.id == assignee_data.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Проверяем, не назначен ли уже этот пользователь
    if user in task.assignees:
        raise HTTPException(status_code=400, detail="User already assigned to this task")

    # Добавляем исполнителя
    task.assignees.append(user)
    db.commit()

    # Отправляем уведомление новому исполнителю
    try:
        from bot.handlers import notify_assigned_user
        from bot.main import bot
        import asyncio

        asyncio.create_task(notify_assigned_user(bot, task_id, db, assignee=user))
    except Exception as e:
        logger.error(f"Failed to send assignment notification: {e}")

    return {
        "id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "message": "Assignee added successfully"
    }


@app.delete("/api/tasks/{task_id}/assignees/{user_id}")
async def remove_task_assignee(task_id: int, user_id: int, db: Session = Depends(get_db)):
    """Удалить исполнителя из задачи"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Проверяем, назначен ли этот пользователь
    if user not in task.assignees:
        raise HTTPException(status_code=400, detail="User is not assigned to this task")

    # Удаляем исполнителя
    task.assignees.remove(user)
    db.commit()

    return {"message": "Assignee removed successfully"}


@app.get("/api/oauth/google/start")
async def google_oauth_start(user_id: int, db: Session = Depends(get_db)):
    if not GOOGLE_OAUTH_CLIENT_ID or not GOOGLE_OAUTH_CLIENT_SECRET or not GOOGLE_OAUTH_REDIRECT_URI:
        raise HTTPException(status_code=500, detail="Google OAuth is not configured")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    state = _build_oauth_state(user_id)
    params = urlparse.urlencode({
        "client_id": GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": GOOGLE_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email https://mail.google.com/",
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })
    return RedirectResponse(url=f"{GOOGLE_OAUTH_AUTH_URL}?{params}")


@app.get("/api/oauth/google/callback", response_class=HTMLResponse)
async def google_oauth_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    db: Session = Depends(get_db),
):
    if error:
        return _oauth_result_html(False, f"Google OAuth error: {error}")
    if not code or not state:
        return _oauth_result_html(False, "Missing OAuth parameters")

    try:
        user_id = _verify_oauth_state(state)
    except Exception as e:
        logger.error(f"OAuth state validation failed: {e}")
        return _oauth_result_html(False, "OAuth state is invalid or expired")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return _oauth_result_html(False, "User not found", user_id=user_id)

    try:
        token_payload = _exchange_google_code(code)
    except Exception as e:
        logger.error(f"Google token exchange failed: {e}")
        return _oauth_result_html(False, "Failed to exchange OAuth code", user_id=user.id)

    access_token = token_payload.get("access_token")
    refresh_token = token_payload.get("refresh_token")
    if not access_token:
        return _oauth_result_html(False, "Google did not return access_token", user_id=user.id)

    try:
        email_address = _fetch_google_email(access_token)
    except Exception as e:
        logger.error(f"Failed to fetch Google profile email: {e}")
        return _oauth_result_html(False, "Failed to read Google account email", user_id=user.id)

    try:
        existing = db.query(EmailAccount).filter(EmailAccount.email_address == email_address).first()
        if existing and existing.user_id != user.id:
            return _oauth_result_html(False, "This Google email is already linked to another user", user_id=user.id)

        if existing:
            if refresh_token:
                existing.imap_password = f"{GOOGLE_REFRESH_PREFIX}{refresh_token}"
            existing.imap_server = "imap.gmail.com"
            existing.imap_port = 993
            existing.imap_username = email_address
            existing.use_ssl = True
            existing.folder = "INBOX"
            existing.is_active = True
            existing.updated_at = datetime.utcnow()
            db.commit()
            return _oauth_result_html(True, f"Email {email_address} connected", user_id=user.id)

        if not refresh_token:
            return _oauth_result_html(False, "Google did not return refresh_token. Try connect again.", user_id=user.id)

        accounts_count = db.query(EmailAccount).filter(EmailAccount.user_id == user.id).count()
        if accounts_count >= 5:
            return _oauth_result_html(False, "Maximum 5 email accounts per user", user_id=user.id)

        account = EmailAccount(
            user_id=user.id,
            email_address=email_address,
            imap_server="imap.gmail.com",
            imap_port=993,
            imap_username=email_address,
            imap_password=f"{GOOGLE_REFRESH_PREFIX}{refresh_token}",
            use_ssl=True,
            folder="INBOX",
            is_active=True,
            auto_confirm=False,
            last_uid=0,
        )
        db.add(account)
        db.commit()
        return _oauth_result_html(True, f"Email {email_address} connected", user_id=user.id)
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to save Google OAuth account: {e}", exc_info=True)
        return _oauth_result_html(False, "Failed to save account", user_id=user.id)


# ============================================================
# Email Account Management API
# ============================================================

class EmailAccountCreate(BaseModel):
    """Модель для создания email аккаунта"""
    email_address: str
    imap_server: str
    imap_port: int = 993
    imap_username: str
    imap_password: str
    use_ssl: bool = True
    folder: str = "INBOX"
    auto_confirm: bool = False
    only_from_addresses: Optional[List[str]] = None
    subject_keywords: Optional[List[str]] = None


class EmailAccountUpdate(BaseModel):
    """Модель для обновления email аккаунта"""
    is_active: Optional[bool] = None
    auto_confirm: Optional[bool] = None
    folder: Optional[str] = None
    only_from_addresses: Optional[List[str]] = None
    subject_keywords: Optional[List[str]] = None
    imap_password: Optional[str] = None


class EmailAccountTest(BaseModel):
    """Модель для тестирования подключения"""
    email_address: str
    imap_server: str
    imap_port: int = 993
    imap_username: str
    imap_password: str
    use_ssl: bool = True





@app.get("/api/oauth/yandex/start")
async def yandex_oauth_start(user_id: int, db: Session = Depends(get_db)):
    if not YANDEX_OAUTH_CLIENT_ID or not YANDEX_OAUTH_CLIENT_SECRET or not YANDEX_OAUTH_REDIRECT_URI:
        raise HTTPException(status_code=500, detail="Yandex OAuth is not configured")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    state = _build_oauth_state(user_id)
    params = urlparse.urlencode({
        "response_type": "code",
        "client_id": YANDEX_OAUTH_CLIENT_ID,
        "redirect_uri": YANDEX_OAUTH_REDIRECT_URI,
        "force_confirm": "yes",
        "state": state,
    })
    return RedirectResponse(url=f"{YANDEX_OAUTH_AUTH_URL}?{params}")


@app.get("/api/oauth/yandex/callback", response_class=HTMLResponse)
async def yandex_oauth_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    db: Session = Depends(get_db),
):
    if error:
        return _oauth_result_html(False, f"Yandex OAuth error: {error}")
    if not code or not state:
        return _oauth_result_html(False, "Missing OAuth parameters")

    try:
        user_id = _verify_oauth_state(state)
    except Exception as e:
        logger.error(f"OAuth state validation failed: {e}")
        return _oauth_result_html(False, "OAuth state is invalid or expired")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return _oauth_result_html(False, "User not found", user_id=user_id)

    try:
        token_payload = _exchange_yandex_code(code)
    except Exception as e:
        logger.error(f"Yandex token exchange failed: {e}")
        return _oauth_result_html(False, "Failed to exchange OAuth code", user_id=user.id)

    access_token = token_payload.get("access_token")
    refresh_token = token_payload.get("refresh_token")
    if not access_token:
        return _oauth_result_html(False, "Yandex did not return access_token", user_id=user.id)

    try:
        email_address = _fetch_yandex_email(access_token)
    except Exception as e:
        logger.error(f"Failed to fetch Yandex profile email: {e}")
        return _oauth_result_html(False, "Failed to read Yandex account email", user_id=user.id)

    try:
        existing = db.query(EmailAccount).filter(EmailAccount.email_address == email_address).first()
        if existing and existing.user_id != user.id:
            return _oauth_result_html(False, "This Yandex email is already linked to another user", user_id=user.id)

        if existing:
            if refresh_token:
                existing.imap_password = f"{YANDEX_REFRESH_PREFIX}{refresh_token}"
            existing.imap_server = "imap.yandex.ru"
            existing.imap_port = 993
            existing.imap_username = email_address
            existing.use_ssl = True
            existing.folder = "INBOX"
            existing.is_active = True
            existing.updated_at = datetime.utcnow()
            db.commit()
            return _oauth_result_html(True, f"Email {email_address} connected", user_id=user.id)

        if not refresh_token:
            return _oauth_result_html(False, "Yandex did not return refresh_token. Try connect again.", user_id=user.id)

        accounts_count = db.query(EmailAccount).filter(EmailAccount.user_id == user.id).count()
        if accounts_count >= 5:
            return _oauth_result_html(False, "Maximum 5 email accounts per user", user_id=user.id)

        account = EmailAccount(
            user_id=user.id,
            email_address=email_address,
            imap_server="imap.yandex.ru",
            imap_port=993,
            imap_username=email_address,
            imap_password=f"{YANDEX_REFRESH_PREFIX}{refresh_token}",
            use_ssl=True,
            folder="INBOX",
            is_active=True,
            auto_confirm=False,
            last_uid=0,
        )
        db.add(account)
        db.commit()
        return _oauth_result_html(True, f"Email {email_address} connected", user_id=user.id)
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to save Yandex OAuth account: {e}", exc_info=True)
        return _oauth_result_html(False, "Failed to save account", user_id=user.id)


@app.get("/api/email-accounts", response_model=List[dict])
async def get_email_accounts(user_id: Optional[int] = None, db: Session = Depends(get_db)):
    """
    Получить все email аккаунты пользователя
    """
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id parameter is required")

    accounts = db.query(EmailAccount).filter(EmailAccount.user_id == user_id).all()

    result = []
    for account in accounts:
        # Подсчитываем статистику
        total_messages = db.query(EmailMessage).filter(
            EmailMessage.email_account_id == account.id
        ).count()

        processed_messages = db.query(EmailMessage).filter(
            EmailMessage.email_account_id == account.id,
            EmailMessage.processed == True
        ).count()

        tasks_created = db.query(EmailMessage).filter(
            EmailMessage.email_account_id == account.id,
            EmailMessage.task_id.isnot(None)
        ).count()

        result.append({
            "id": account.id,
            "email_address": account.email_address,
            "imap_server": account.imap_server,
            "imap_port": account.imap_port,
            "imap_username": account.imap_username,
            "use_ssl": account.use_ssl,
            "folder": account.folder,
            "is_active": account.is_active,
            "auto_confirm": account.auto_confirm,
            "last_checked": format_datetime_utc(account.last_checked),
            "last_uid": account.last_uid,
            "only_from_addresses": account.only_from_addresses or [],
            "subject_keywords": account.subject_keywords or [],
            "created_at": format_datetime_utc(account.created_at),
            "updated_at": format_datetime_utc(account.updated_at),
            "stats": {
                "total_messages": total_messages,
                "processed_messages": processed_messages,
                "tasks_created": tasks_created
            }
        })

    return result


@app.post("/api/email-accounts", response_model=dict)
async def create_email_account(account_data: EmailAccountCreate, user_id: int, db: Session = Depends(get_db)):
    """
    Создать новый email аккаунт
    """
    # Проверяем существование пользователя
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Проверяем не существует ли уже такой email
    existing = db.query(EmailAccount).filter(
        EmailAccount.email_address == account_data.email_address
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail="Email account already exists")

    # Проверяем лимит (5 аккаунтов на пользователя)
    accounts_count = db.query(EmailAccount).filter(EmailAccount.user_id == user_id).count()
    if accounts_count >= 5:
        raise HTTPException(status_code=400, detail="Maximum 5 email accounts per user")

    # Тестируем подключение перед сохранением
    from bot.email_handler import test_imap_connection

    success, error_message = test_imap_connection(
        server=account_data.imap_server,
        port=account_data.imap_port,
        username=account_data.imap_username,
        password=account_data.imap_password,
        use_ssl=account_data.use_ssl
    )

    if not success:
        raise HTTPException(status_code=400, detail=f"IMAP connection failed: {error_message}")

    # Создаем аккаунт
    new_account = EmailAccount(
        user_id=user_id,
        email_address=account_data.email_address,
        imap_server=account_data.imap_server,
        imap_port=account_data.imap_port,
        imap_username=account_data.imap_username,
        imap_password=account_data.imap_password,
        use_ssl=account_data.use_ssl,
        folder=account_data.folder,
        is_active=True,
        auto_confirm=account_data.auto_confirm,
        only_from_addresses=account_data.only_from_addresses,
        subject_keywords=account_data.subject_keywords,
        last_uid=0
    )

    db.add(new_account)
    db.commit()
    db.refresh(new_account)

    return {
        "id": new_account.id,
        "email_address": new_account.email_address,
        "message": "Email account created successfully"
    }


@app.put("/api/email-accounts/{account_id}", response_model=dict)
async def update_email_account(
    account_id: int,
    account_data: EmailAccountUpdate,
    db: Session = Depends(get_db)
):
    """
    Обновить настройки email аккаунта
    """
    account = db.query(EmailAccount).filter(EmailAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Email account not found")

    # Обновляем поля
    if account_data.is_active is not None:
        account.is_active = account_data.is_active

    if account_data.auto_confirm is not None:
        account.auto_confirm = account_data.auto_confirm

    if account_data.folder is not None:
        account.folder = account_data.folder

    if account_data.only_from_addresses is not None:
        account.only_from_addresses = account_data.only_from_addresses

    if account_data.subject_keywords is not None:
        account.subject_keywords = account_data.subject_keywords

    if account_data.imap_password is not None:
        # Если меняется пароль - тестируем подключение
        from bot.email_handler import test_imap_connection

        success, error_message = test_imap_connection(
            server=account.imap_server,
            port=account.imap_port,
            username=account.imap_username,
            password=account_data.imap_password,
            use_ssl=account.use_ssl
        )

        if not success:
            raise HTTPException(status_code=400, detail=f"IMAP connection failed: {error_message}")

        account.imap_password = account_data.imap_password

    db.commit()

    return {"message": "Email account updated successfully"}


@app.delete("/api/email-accounts/{account_id}")
async def delete_email_account(account_id: int, db: Session = Depends(get_db)):
    """
    Удалить email аккаунт
    """
    account = db.query(EmailAccount).filter(EmailAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Email account not found")

    db.delete(account)
    db.commit()

    return {"message": "Email account deleted successfully"}


@app.post("/api/email-accounts/test", response_model=dict)
async def test_email_connection(test_data: EmailAccountTest):
    """
    Тестировать IMAP подключение без сохранения
    """
    from bot.email_handler import test_imap_connection

    success, error_message = test_imap_connection(
        server=test_data.imap_server,
        port=test_data.imap_port,
        username=test_data.imap_username,
        password=test_data.imap_password,
        use_ssl=test_data.use_ssl
    )

    if success:
        return {
            "success": True,
            "message": "Connection successful"
        }
    else:
        return {
            "success": False,
            "message": error_message
        }


@app.get("/api/email-accounts/{account_id}/messages", response_model=List[dict])
async def get_email_messages(
    account_id: int,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """
    Получить историю обработанных email сообщений
    """
    account = db.query(EmailAccount).filter(EmailAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Email account not found")

    messages = db.query(EmailMessage).filter(
        EmailMessage.email_account_id == account_id
    ).order_by(desc(EmailMessage.date)).limit(limit).offset(offset).all()

    result = []
    for msg in messages:
        attachments = []
        for attachment in msg.attachments:
            attachments.append({
                "id": attachment.id,
                "filename": attachment.filename,
                "content_type": attachment.content_type,
                "file_size": attachment.file_size,
                "has_extracted_text": bool(attachment.extracted_text)
            })

        result.append({
            "id": msg.id,
            "message_id": msg.message_id,
            "subject": msg.subject,
            "from_address": msg.from_address,
            "to_address": msg.to_address,
            "date": format_datetime_utc(msg.date),
            "body_text": msg.body_text,
            "has_attachments": msg.has_attachments,
            "attachments": attachments,
            "processed": msg.processed,
            "processed_at": format_datetime_utc(msg.processed_at),
            "task_id": msg.task_id,
            "error_message": msg.error_message,
            "created_at": format_datetime_utc(msg.created_at)
        })

    return result


@app.get("/api/email-attachments/{attachment_id}/download")
async def download_email_attachment(attachment_id: int, db: Session = Depends(get_db)):
    attachment = db.query(EmailAttachment).filter(EmailAttachment.id == attachment_id).first()
    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")

    headers = {
        "Content-Disposition": f'attachment; filename="{attachment.filename}"'
    }

    return Response(
        content=attachment.file_data,
        media_type=attachment.content_type or "application/octet-stream",
        headers=headers
    )
