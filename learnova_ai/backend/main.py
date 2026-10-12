"""
FastAPI backend. Each concern lives in backend/services/*; auth lives in
backend/auth.py; this file is routing + persistence glue.

Run with:
    uvicorn backend.main:app --reload
"""

import os
import json
import shutil
import logging
import datetime
import uuid
import base64
import requests
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Request, Header
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from backend.database import get_db, init_db, SessionLocal
from backend import models, auth
from backend.services import document_service, syllabus_service, rag_service, ai_service, notification_service

logger = logging.getLogger("studyhub")

DOCS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "documents")
os.makedirs(DOCS_DIR, exist_ok=True)

app = FastAPI(title="Learnova AI")

# In development the Vite frontend normally runs on :5173. In production
# this should be set to the deployed frontend origin(s), comma-separated.
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5500,http://127.0.0.1:5500").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "25")) * 1024 * 1024
ALLOWED_EXTENSIONS = {"pdf", "docx", "pptx", "txt"}


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Without this, an unhandled exception anywhere in a route makes
    Starlette return a PLAIN-TEXT 500 body ("Internal Server Error"), which
    breaks any client calling response.json() on it — that's what produced
    the JSONDecodeError in the frontend. Every error response from this API
    is now guaranteed to be JSON, and the real traceback goes to the server
    log instead of the client."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": f"Server error: {exc.__class__.__name__}: {exc}"})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


_scheduler = None


@app.on_event("startup")
def on_startup():
    init_db()
    global _scheduler
    _scheduler = notification_service.start_scheduler(SessionLocal)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class SignupRequest(BaseModel):
    username: str
    email: EmailStr
    password: str


class SettingsUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[EmailStr] = None


class CourseCreate(BaseModel):
    name: str
    subject_hint: str = ""


class CourseUpdate(BaseModel):
    name: Optional[str] = None
    subject_hint: Optional[str] = None


class DeadlineUpdate(BaseModel):
    title: Optional[str] = None
    item_type: Optional[str] = None
    due_date: Optional[str] = None


class DeadlineCreate(BaseModel):
    title: str
    item_type: str = "assignment"
    due_date: str  # YYYY-MM-DD


class AskRequest(BaseModel):
    question: str


class StudyRequest(BaseModel):
    text: Optional[str] = None
    document_id: Optional[str] = None


def days_until(due_date_str: str) -> int:
    return (datetime.date.fromisoformat(due_date_str) - datetime.date.today()).days


def _get_owned_course(course_id: str, user: models.User, db: Session) -> models.Course:
    course = db.query(models.Course).filter(models.Course.id == course_id, models.Course.owner_id == user.id).first()
    if not course:
        raise HTTPException(404, "Course not found")
    return course


def _resolve_source_text(course: models.Course, req: StudyRequest, db: Session) -> str:
    if req.text and req.text.strip():
        return req.text
    if req.document_id:
        doc = db.query(models.Document).filter(models.Document.id == req.document_id, models.Document.course_id == course.id).first()
        if doc:
            return doc.raw_text
    raise HTTPException(400, "Provide either 'text' or a valid 'document_id'.")


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@app.post("/auth/signup")
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    if db.query(models.User).filter(models.User.email == payload.email).first():
        raise HTTPException(400, "An account with that email already exists.")
    if len(payload.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    if len(payload.password.encode("utf-8")) > 72:
        raise HTTPException(400, "Password must be at most 72 characters.")
    username = payload.username.strip()
    if len(username) < 3 or len(username) > 30 or not username.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(400, "Username must be 3-30 characters and use only letters, numbers, _ or -.")
    if db.query(models.User).filter(models.User.username == username).first():
        raise HTTPException(400, "That username is already taken.")
    user = models.User(username=username, email=payload.email, hashed_password=auth.hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    token = auth.create_access_token(user.id)
    return {"access_token": token, "token_type": "bearer", "email": user.email, "username": user.username}


@app.post("/auth/login")
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # OAuth2PasswordRequestForm uses "username" as the field name; students sign
    # in with their email, so we just treat that field as the email address.
    user = db.query(models.User).filter((models.User.username == form.username) | (models.User.email == form.username)).first()
    if not user or not auth.verify_password(form.password, user.hashed_password):
        raise HTTPException(401, "Incorrect email or password.")
    token = auth.create_access_token(user.id)
    return {"access_token": token, "token_type": "bearer", "email": user.email, "username": user.username}


@app.get("/auth/me")
def me(current_user: models.User = Depends(auth.get_current_user)):
    return {
        "username": current_user.username,
        "email": current_user.email,
        "profile_photo_url": current_user.profile_photo_url,
        "ai_assistant_available": ai_service.is_available(),
    }


@app.patch("/auth/me")
def update_me(payload: SettingsUpdate, current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    values = payload.dict(exclude_unset=True)
    if "email" in values and values["email"] is not None:
        email = str(values["email"]).strip().lower()
        existing_email = db.query(models.User).filter(models.User.email == email, models.User.id != current_user.id).first()
        if existing_email:
            raise HTTPException(400, "That email address is already in use.")
        values["email"] = email
    if "username" in values and values["username"] is not None:
        username = values["username"].strip()
        if len(username) < 3 or len(username) > 30 or not username.replace("_", "").replace("-", "").isalnum():
            raise HTTPException(400, "Username must be 3-30 characters and use only letters, numbers, _ or -.")
        existing = db.query(models.User).filter(models.User.username == username, models.User.id != current_user.id).first()
        if existing:
            raise HTTPException(400, "That username is already taken.")
        values["username"] = username
    for field, value in values.items():
        if value is not None:
            setattr(current_user, field, value)
    db.commit()
    db.refresh(current_user)
    return {"ok": True, "username": current_user.username, "email": current_user.email, "profile_photo_url": current_user.profile_photo_url}


@app.post("/auth/me/photo")
async def update_profile_photo(file: UploadFile = File(...), current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    allowed = {"image/png": "png", "image/jpeg": "jpeg", "image/webp": "webp", "image/gif": "gif"}
    if file.content_type not in allowed:
        raise HTTPException(400, "Profile photo must be a PNG, JPEG, WEBP, or GIF image.")
    data = await file.read(2 * 1024 * 1024 + 1)
    if not data or len(data) > 2 * 1024 * 1024:
        raise HTTPException(400, "Profile photo must be smaller than 2 MB.")
    encoded = base64.b64encode(data).decode("ascii")
    current_user.profile_photo_url = f"data:{file.content_type};base64,{encoded}"
    db.commit()
    db.refresh(current_user)
    return {"ok": True, "profile_photo_url": current_user.profile_photo_url}


@app.delete("/auth/me/photo")
def delete_profile_photo(current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    current_user.profile_photo_url = None
    db.commit()
    return {"ok": True}


@app.get("/diagnostics/gemini")
def diagnostics_gemini(current_user: models.User = Depends(auth.get_current_user)):
    """Actually calls Gemini with a trivial prompt and reports what happened —
    for telling apart 'no key set', 'bad key', 'wrong model name', and
    'network/quota issue' without digging through server logs. The key
    itself is never included in the response."""
    if not ai_service.GEMINI_API_KEY:
        return {
            "ok": False,
            "reason": "GEMINI_API_KEY is not set on the server. Add it to your .env file "
                      "(same folder as backend/), then restart the backend.",
        }
    try:
        reply = ai_service._call_gemini("Reply with exactly one word: OK")
        return {"ok": True, "model": ai_service.GEMINI_MODEL, "sample_reply": reply}
    except requests.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else None
        body = e.response.text[:500] if e.response is not None else ""
        hint = {
            400: "Request was malformed — unexpected, please report this.",
            403: "The key was rejected (invalid, disabled, or missing Generative Language API access).",
            404: f"Model '{ai_service.GEMINI_MODEL}' isn't available for this key/API version — try a different GEMINI_MODEL.",
            429: "Rate limit or quota exceeded for this key.",
        }.get(status_code, "Unexpected error calling Gemini.")
        return {"ok": False, "status_code": status_code, "hint": hint, "model": ai_service.GEMINI_MODEL, "raw_response": body}
    except requests.RequestException as e:
        return {"ok": False, "reason": f"Network error reaching Gemini: {e}"}


# ---------------------------------------------------------------------------
# Courses
# ---------------------------------------------------------------------------

@app.post("/courses")
def create_course(payload: CourseCreate, current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    course = models.Course(owner_id=current_user.id, name=payload.name, subject_hint=payload.subject_hint)
    db.add(course)
    db.commit()
    db.refresh(course)
    return {"id": course.id, "name": course.name, "subject_hint": course.subject_hint}


@app.get("/courses")
def list_courses(current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    courses = db.query(models.Course).filter(models.Course.owner_id == current_user.id).order_by(models.Course.created_at).all()
    out = []
    for c in courses:
        upcoming = sum(1 for it in c.deadlines if days_until(it.due_date) >= 0)
        out.append({
            "id": c.id, "name": c.name, "subject_hint": c.subject_hint,
            "document_count": len(c.documents), "upcoming_deadlines": upcoming,
        })
    return out


@app.patch("/courses/{course_id}")
def update_course(course_id: str, payload: CourseUpdate, current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    course = _get_owned_course(course_id, current_user, db)
    values = payload.dict(exclude_unset=True)
    if "name" in values:
        if not values["name"] or not values["name"].strip():
            raise HTTPException(400, "Course name cannot be empty.")
        course.name = values["name"].strip()
    if "subject_hint" in values and values["subject_hint"] is not None:
        course.subject_hint = values["subject_hint"].strip()
    db.commit()
    db.refresh(course)
    return {"id": course.id, "name": course.name, "subject_hint": course.subject_hint}


@app.delete("/courses/{course_id}")
def delete_course(course_id: str, current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    course = _get_owned_course(course_id, current_user, db)
    db.delete(course)
    db.commit()
    rag_service.delete_course_index(course_id)
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Documents (syllabus / handout / slide ingestion -> RAG + auto deadlines)
# ---------------------------------------------------------------------------

@app.post("/courses/{course_id}/documents")
async def upload_document(course_id: str, file: UploadFile = File(...),
                     current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    course = _get_owned_course(course_id, current_user, db)

    original_name = os.path.basename(file.filename or "upload")
    ext = os.path.splitext(original_name)[1].lstrip(".").lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, "Unsupported file type. Allowed: PDF, DOCX, PPTX, TXT.")

    course_dir = os.path.join(DOCS_DIR, course_id)
    os.makedirs(course_dir, exist_ok=True)
    safe_stem = os.path.splitext(original_name)[0].replace("/", "_").replace("\\", "_")[:120] or "document"
    unique_name = f"{uuid.uuid4().hex}_{safe_stem}.{ext}"
    dest_path = os.path.join(course_dir, unique_name)

    total = 0
    with open(dest_path, "wb") as f:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                f.close()
                if os.path.exists(dest_path):
                    os.remove(dest_path)
                raise HTTPException(413, f"File is too large. Maximum is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
            f.write(chunk)

    try:
        text = document_service.extract_text_from_path(dest_path)
    except document_service.UnsupportedFileError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))

    document = models.Document(course_id=course_id, filename=original_name, source_type=ext, raw_text=text)
    db.add(document)
    db.commit()
    db.refresh(document)

    # Chunk + index for RAG — only the NEW chunks are embedded and appended;
    # every previously indexed chunk's vector is left untouched.
    chunk_texts = rag_service.chunk_text(text)
    new_chunks = []
    for i, chunk_text in enumerate(chunk_texts):
        chunk = models.DocumentChunk(document_id=document.id, course_id=course_id, chunk_index=i, text=chunk_text)
        db.add(chunk)
        new_chunks.append(chunk)
    db.commit()
    for chunk in new_chunks:
        db.refresh(chunk)
    rag_service.add_chunks_to_index(course_id, new_chunks, db)

    # Automatic deadline extraction. High-confidence hits (explicit keyword +
    # explicit year) are auto-confirmed; anything less certain is still
    # created, but flagged "pending_review" so the student sees and confirms
    # it rather than silently trusting the heuristic.
    candidates = syllabus_service.extract_deadlines_from_text(text)
    existing = {(it.title.lower(), it.due_date) for it in course.deadlines}
    added = []
    for c in candidates:
        key = (c["title"].lower(), c["due_date"])
        if key in existing:
            continue
        status = "confirmed" if c["confidence"] == "high" else "pending_review"
        item = models.DeadlineItem(
            course_id=course_id, title=c["title"], item_type=c["item_type"], due_date=c["due_date"],
            source="auto", status=status, confidence=c["confidence"], source_line=c["source_line"],
        )
        db.add(item)
        added.append(c)
        existing.add(key)
    db.commit()

    return {
        "document_id": document.id,
        "filename": document.filename,
        "characters_extracted": len(text),
        "chunks_indexed": len(chunk_texts),
        "deadlines_auto_added": added,
    }


@app.get("/courses/{course_id}/documents")
def list_documents(course_id: str, current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    course = _get_owned_course(course_id, current_user, db)
    docs = db.query(models.Document).filter(models.Document.course_id == course.id).order_by(models.Document.uploaded_at.desc()).all()
    return [{"id": d.id, "filename": d.filename, "source_type": d.source_type,
             "uploaded_at": d.uploaded_at.isoformat(), "preview": d.raw_text[:300]} for d in docs]


@app.get("/documents/{document_id}/open")
def open_document(document_id: str, current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    """Return the stored original file for an authenticated document owner."""
    doc = (db.query(models.Document)
        .join(models.Course, models.Document.course_id == models.Course.id)
        .filter(models.Document.id == document_id, models.Course.owner_id == current_user.id)
        .first())
    if not doc:
        raise HTTPException(404, "Document not found")
    stored_dir = os.path.join(DOCS_DIR, doc.course_id)
    suffix = "_" + doc.filename
    path = next((os.path.join(stored_dir, name) for name in os.listdir(stored_dir)
                 if name.endswith(suffix) and os.path.isfile(os.path.join(stored_dir, name))), None) if os.path.isdir(stored_dir) else None
    if not path:
        raise HTTPException(404, "Original file is missing on the server. Upload this document again.")
    media_types = {"pdf": "application/pdf", "txt": "text/plain; charset=utf-8",
                   "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                   "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation"}
    return FileResponse(path, media_type=media_types.get(doc.source_type, "application/octet-stream"),
                        filename=doc.filename, content_disposition_type="inline" if doc.source_type in {"pdf", "txt"} else "attachment")


@app.delete("/documents/{document_id}")
def delete_document(document_id: str, current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    doc = (
        db.query(models.Document)
        .join(models.Course, models.Document.course_id == models.Course.id)
        .filter(models.Document.id == document_id, models.Course.owner_id == current_user.id)
        .first()
    )
    if not doc:
        raise HTTPException(404, "Document not found")
    course_id = doc.course_id
    stored_dir = os.path.join(DOCS_DIR, course_id)
    # Stored files are server-generated, so only remove files matching the
    # document's original name suffix. If not found, DB/RAG cleanup still works.
    for name in os.listdir(stored_dir) if os.path.isdir(stored_dir) else []:
        if name.endswith("_" + doc.filename):
            try:
                os.remove(os.path.join(stored_dir, name))
            except OSError:
                logger.warning("Could not remove stored document file %s", name)
    db.query(models.DocumentChunk).filter(models.DocumentChunk.document_id == doc.id).delete(synchronize_session=False)
    db.delete(doc)
    db.commit()
    rag_service.rebuild_course_index(course_id, db)
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Deadlines
# ---------------------------------------------------------------------------

@app.post("/courses/{course_id}/deadlines")
def add_deadline(course_id: str, payload: DeadlineCreate,
                  current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    course = _get_owned_course(course_id, current_user, db)
    try:
        datetime.date.fromisoformat(payload.due_date)
    except ValueError:
        raise HTTPException(400, "due_date must be YYYY-MM-DD")
    item = models.DeadlineItem(course_id=course.id, title=payload.title, item_type=payload.item_type,
                                due_date=payload.due_date, source="manual", status="confirmed", confidence="high")
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"id": item.id, "title": item.title, "item_type": item.item_type, "due_date": item.due_date}


@app.get("/courses/{course_id}/deadlines")
def list_deadlines(course_id: str, current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    course = _get_owned_course(course_id, current_user, db)
    items = db.query(models.DeadlineItem).filter(models.DeadlineItem.course_id == course.id).order_by(models.DeadlineItem.due_date).all()
    return [{"id": i.id, "title": i.title, "item_type": i.item_type, "due_date": i.due_date,
             "source": i.source, "status": i.status, "confidence": i.confidence,
             "source_line": i.source_line, "days_until": days_until(i.due_date)} for i in items]


def _get_owned_deadline(item_id: str, current_user: models.User, db: Session) -> models.DeadlineItem:
    item = (
        db.query(models.DeadlineItem)
        .join(models.Course, models.DeadlineItem.course_id == models.Course.id)
        .filter(models.DeadlineItem.id == item_id, models.Course.owner_id == current_user.id)
        .first()
    )
    if not item:
        raise HTTPException(404, "Deadline not found")
    return item


@app.patch("/deadlines/{item_id}")
def update_deadline(item_id: str, payload: DeadlineUpdate, current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    item = _get_owned_deadline(item_id, current_user, db)
    values = payload.dict(exclude_unset=True)
    if "title" in values:
        if not values["title"] or not values["title"].strip():
            raise HTTPException(400, "Deadline title cannot be empty.")
        item.title = values["title"].strip()
    if "item_type" in values and values["item_type"] is not None:
        item.item_type = values["item_type"].strip()
    if "due_date" in values and values["due_date"] is not None:
        try:
            datetime.date.fromisoformat(values["due_date"])
        except ValueError:
            raise HTTPException(400, "due_date must be YYYY-MM-DD")
        item.due_date = values["due_date"]
    db.commit()
    return {"ok": True}


@app.patch("/deadlines/{item_id}/confirm")
def confirm_deadline(item_id: str, current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    """Student confirms a low/medium-confidence auto-extracted deadline is correct."""
    item = _get_owned_deadline(item_id, current_user, db)
    item.status = "confirmed"
    db.commit()
    return {"ok": True}


@app.delete("/deadlines/{item_id}")
def delete_deadline(item_id: str, current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    item = _get_owned_deadline(item_id, current_user, db)
    db.delete(item)
    db.commit()
    return {"deleted": True}


@app.get("/dashboard")
def dashboard(current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    """Semester-wide view across every one of this student's courses, sorted
    soonest first. Used to populate the dashboard deadline list."""
    rows = (
        db.query(models.DeadlineItem, models.Course)
        .join(models.Course, models.DeadlineItem.course_id == models.Course.id)
        .filter(models.Course.owner_id == current_user.id)
        .all()
    )
    out = []
    for item, course in rows:
        out.append({
            "course_id": course.id, "course_name": course.name,
            "item_id": item.id, "title": item.title, "item_type": item.item_type,
            "due_date": item.due_date, "days_until": days_until(item.due_date),
            "source": item.source, "status": item.status,
        })
    out.sort(key=lambda r: r["days_until"])
    return out


# ---------------------------------------------------------------------------
# Notifications (exactly 2 days before)
# ---------------------------------------------------------------------------

@app.post("/notifications/check")
def notifications_check(x_scheduler_key: Optional[str] = Header(default=None), db: Session = Depends(get_db)):
    """Manual trigger for the daily scan. Protected because the scan is global."""
    expected = os.getenv("NOTIFICATION_JOB_KEY", "")
    if not expected or x_scheduler_key != expected:
        raise HTTPException(403, "Notification job endpoint is protected.")
    created = notification_service.check_and_create_notifications(db)
    return {"created": len(created)}


@app.get("/notifications")
def list_notifications(unread_only: bool = True, current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    q = (
        db.query(models.Notification)
        .join(models.Course, models.Notification.course_id == models.Course.id)
        .filter(models.Course.owner_id == current_user.id)
    )
    if unread_only:
        q = q.filter(models.Notification.is_read == False)  # noqa: E712
    notes = q.order_by(models.Notification.created_at.desc()).all()
    result = [{"id": n.id, "course_id": n.course_id, "message": n.message,
               "created_at": n.created_at.isoformat(), "is_read": n.is_read, "kind": "reminder"} for n in notes]
    today = datetime.date.today()
    deadline_query = (db.query(models.DeadlineItem, models.Course)
        .join(models.Course, models.DeadlineItem.course_id == models.Course.id)
        .filter(models.Course.owner_id == current_user.id))
    for item, course in deadline_query.all():
        try:
            due = datetime.date.fromisoformat(item.due_date)
            days_left = (due - today).days
        except (ValueError, TypeError):
            continue
        if days_left > 7:
            continue
        if days_left < 0:
            message = f'OVERDUE: "{item.title}" ({item.item_type}) for {course.name} was due on {item.due_date}.'
        elif days_left == 0:
            message = f'DUE TODAY: "{item.title}" ({item.item_type}) for {course.name} is due today.'
        elif days_left == 1:
            message = f'DUE TOMORROW: "{item.title}" ({item.item_type}) for {course.name} is due tomorrow ({item.due_date}).'
        else:
            message = f'Upcoming deadline: "{item.title}" ({item.item_type}) for {course.name} is due in {days_left} days, on {item.due_date}.'
        result.append({"id": f"deadline-{item.id}", "course_id": course.id, "message": message,
                       "created_at": datetime.datetime.combine(today, datetime.time.min).isoformat(),
                       "is_read": bool(item.notification_seen), "kind": "deadline", "due_date": item.due_date, "days_until": days_left})
    result.sort(key=lambda n: (n.get("days_until", 999), n["created_at"]), reverse=False)
    if unread_only:
        result = [n for n in result if not n["is_read"]]
    return result


@app.patch("/notifications/{note_id}/read")
def mark_notification_read(note_id: str, current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    if note_id.startswith("deadline-"):
        deadline_id = note_id.removeprefix("deadline-")
        item = (db.query(models.DeadlineItem)
            .join(models.Course, models.DeadlineItem.course_id == models.Course.id)
            .filter(models.DeadlineItem.id == deadline_id, models.Course.owner_id == current_user.id)
            .first())
        if not item:
            raise HTTPException(404, "Deadline notification not found")
        item.notification_seen = True
        db.commit()
        return {"ok": True, "is_read": True}
    note = (
        db.query(models.Notification)
        .join(models.Course, models.Notification.course_id == models.Course.id)
        .filter(models.Notification.id == note_id, models.Course.owner_id == current_user.id)
        .first()
    )
    if not note:
        raise HTTPException(404, "Notification not found")
    note.is_read = True
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# AI study assistant (RAG + persistent memory)
# ---------------------------------------------------------------------------

@app.post("/courses/{course_id}/assistant/ask")
def ask_assistant(course_id: str, payload: AskRequest,
                   current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    course = _get_owned_course(course_id, current_user, db)

    context_chunks = rag_service.retrieve(course.id, payload.question, top_k=5, db=db)
    history = [
        {"role": m.role, "content": m.content}
        for m in db.query(models.ChatMessage).filter(models.ChatMessage.course_id == course.id)
        .order_by(models.ChatMessage.created_at).all()
    ]

    answer, provider = ai_service.answer_question(payload.question, context_chunks, history)

    db.add(models.ChatMessage(course_id=course.id, role="user", content=payload.question))
    db.add(models.ChatMessage(course_id=course.id, role="assistant", content=answer))
    db.commit()

    return {"answer": answer, "provider": provider, "sources": [c["text"][:200] for c in context_chunks]}


@app.get("/courses/{course_id}/assistant/history")
def assistant_history(course_id: str, current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    course = _get_owned_course(course_id, current_user, db)
    msgs = db.query(models.ChatMessage).filter(models.ChatMessage.course_id == course.id).order_by(models.ChatMessage.created_at).all()
    return [{"role": m.role, "content": m.content, "created_at": m.created_at.isoformat()} for m in msgs]


# ---------------------------------------------------------------------------
# Study tools: summaries, flashcards, quizzes
# ---------------------------------------------------------------------------

@app.post("/courses/{course_id}/study/summary")
def study_summary(course_id: str, payload: StudyRequest,
                   current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    course = _get_owned_course(course_id, current_user, db)
    text = _resolve_source_text(course, payload, db)
    summary, provider = ai_service.generate_summary(text)
    _save_artifact(db, course.id, "summary", {"summary": summary})
    return {"summary": summary, "provider": provider}


@app.post("/courses/{course_id}/study/flashcards")
def study_flashcards(course_id: str, payload: StudyRequest,
                      current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    course = _get_owned_course(course_id, current_user, db)
    text = _resolve_source_text(course, payload, db)
    cards, provider = ai_service.generate_flashcards(text)
    _save_artifact(db, course.id, "flashcards", {"cards": cards})
    return {"cards": cards, "provider": provider}


@app.post("/courses/{course_id}/study/quiz")
def study_quiz(course_id: str, payload: StudyRequest,
               current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    course = _get_owned_course(course_id, current_user, db)
    text = _resolve_source_text(course, payload, db)
    quiz, provider = ai_service.generate_quiz(text)
    _save_artifact(db, course.id, "quiz", {"quiz": quiz})
    return {"quiz": quiz, "provider": provider}


def _save_artifact(db, course_id, kind, content):
    db.add(models.StudyArtifact(course_id=course_id, kind=kind, content_json=json.dumps(content)))
    db.commit()


@app.get("/courses/{course_id}/study/history")
def study_history(course_id: str, current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    course = _get_owned_course(course_id, current_user, db)
    arts = db.query(models.StudyArtifact).filter(models.StudyArtifact.course_id == course.id).order_by(models.StudyArtifact.created_at.desc()).all()
    return [{"id": a.id, "kind": a.kind, "content": json.loads(a.content_json), "created_at": a.created_at.isoformat()} for a in arts]


