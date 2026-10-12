"""
SQLAlchemy models. Courses are entirely student-defined — there is no
fixed subject enum anywhere in the schema. `subject_hint` is free text
the student types (or leaves blank); it can be used as descriptive course context.
"""

import datetime
import uuid

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Boolean, Integer
from sqlalchemy.orm import relationship

from backend.database import Base


def gen_id():
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=gen_id)
    email = Column(String, nullable=False, unique=True, index=True)
    username = Column(String, nullable=False, unique=True, index=True, default="student")
    hashed_password = Column(String, nullable=False)
    profile_photo_url = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    courses = relationship("Course", back_populates="owner", cascade="all, delete-orphan")


class Course(Base):
    __tablename__ = "courses"

    id = Column(String, primary_key=True, default=gen_id)
    owner_id = Column(String, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    subject_hint = Column(String, default="")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    owner = relationship("User", back_populates="courses")
    documents = relationship("Document", back_populates="course", cascade="all, delete-orphan")
    chunks = relationship("DocumentChunk", back_populates="course", cascade="all, delete-orphan")
    deadlines = relationship("DeadlineItem", back_populates="course", cascade="all, delete-orphan")
    messages = relationship("ChatMessage", back_populates="course", cascade="all, delete-orphan")
    artifacts = relationship("StudyArtifact", back_populates="course", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=gen_id)
    course_id = Column(String, ForeignKey("courses.id"), nullable=False)
    filename = Column(String, nullable=False)
    source_type = Column(String, default="")
    raw_text = Column(Text, default="")
    uploaded_at = Column(DateTime, default=datetime.datetime.utcnow)

    course = relationship("Course", back_populates="documents")


class DocumentChunk(Base):
    """One retrievable slice of a document, used by the RAG service.
    `vector_row` is this chunk's row index inside the course's FAISS index."""
    __tablename__ = "document_chunks"

    id = Column(String, primary_key=True, default=gen_id)
    document_id = Column(String, ForeignKey("documents.id"), nullable=False)
    course_id = Column(String, ForeignKey("courses.id"), nullable=False)
    chunk_index = Column(Integer, default=0)
    text = Column(Text, nullable=False)
    vector_row = Column(Integer, nullable=True)

    course = relationship("Course", back_populates="chunks")


class DeadlineItem(Base):
    __tablename__ = "deadline_items"

    id = Column(String, primary_key=True, default=gen_id)
    course_id = Column(String, ForeignKey("courses.id"), nullable=False)
    title = Column(String, nullable=False)
    item_type = Column(String, default="assignment")  # assignment/quiz/exam/reading/project
    due_date = Column(String, nullable=False)  # "YYYY-MM-DD"
    source = Column(String, default="manual")  # "manual" or "auto"
    # "confirmed": manual entries, and high-confidence auto-extractions (explicit year + explicit keyword).
    # "pending_review": auto-extractions the heuristic is less sure about — still created and still
    # counted, but flagged in the UI until the student confirms or removes them.
    status = Column(String, default="confirmed")
    confidence = Column(String, default="high")  # "high" | "medium" | "low" — set by syllabus_service
    source_line = Column(Text, default="")  # the exact syllabus text the extraction came from, for review
    notification_seen = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    course = relationship("Course", back_populates="deadlines")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(String, primary_key=True, default=gen_id)
    deadline_item_id = Column(String, ForeignKey("deadline_items.id"), nullable=False)
    course_id = Column(String, ForeignKey("courses.id"), nullable=False)
    message = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    is_read = Column(Boolean, default=False)
    fired_for_date = Column(String, nullable=False)  # the calendar day this alert was generated on


class ChatMessage(Base):
    """Persistent AI memory: the full assistant conversation per course,
    replayed as context on every new question."""
    __tablename__ = "chat_messages"

    id = Column(String, primary_key=True, default=gen_id)
    course_id = Column(String, ForeignKey("courses.id"), nullable=False)
    role = Column(String, nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    course = relationship("Course", back_populates="messages")


class StudyArtifact(Base):
    """A generated summary / flashcard set / quiz, kept for later review."""
    __tablename__ = "study_artifacts"

    id = Column(String, primary_key=True, default=gen_id)
    course_id = Column(String, ForeignKey("courses.id"), nullable=False)
    kind = Column(String, nullable=False)  # "summary" | "flashcards" | "quiz"
    content_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    course = relationship("Course", back_populates="artifacts")
