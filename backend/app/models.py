from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.utcnow()


class QuestionSet(Base):
    __tablename__ = "question_sets"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(Text)
    file_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    file_type: Mapped[str] = mapped_column(String(16))
    text_content: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    current_phase: Mapped[str] = mapped_column(String(64), default="等待解析")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    parser_version: Mapped[str] = mapped_column(String(32))
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    vocab_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    pages: Mapped[list[DocumentPage]] = relationship(
        back_populates="question_set", cascade="all, delete-orphan"
    )


class DocumentPage(Base):
    __tablename__ = "document_pages"
    __table_args__ = (UniqueConstraint("question_set_id", "page_index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    question_set_id: Mapped[int] = mapped_column(
        ForeignKey("question_sets.id", ondelete="CASCADE"), index=True
    )
    page_index: Mapped[int] = mapped_column(Integer)
    width: Mapped[float] = mapped_column(Float, default=0)
    height: Mapped[float] = mapped_column(Float, default=0)
    raw_text: Mapped[str] = mapped_column(Text, default="")

    question_set: Mapped[QuestionSet] = relationship(back_populates="pages")
    blocks: Mapped[list[ContentBlock]] = relationship(
        back_populates="page", cascade="all, delete-orphan"
    )


class ContentBlock(Base):
    __tablename__ = "content_blocks"
    __table_args__ = (UniqueConstraint("page_id", "block_index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(
        ForeignKey("document_pages.id", ondelete="CASCADE"), index=True
    )
    block_index: Mapped[int] = mapped_column(Integer)
    content_type: Mapped[str] = mapped_column(String(32), index=True)
    section_name: Mapped[str] = mapped_column(String(64), default="unknown")
    text: Mapped[str] = mapped_column(Text)
    x0: Mapped[float] = mapped_column(Float, default=0)
    y0: Mapped[float] = mapped_column(Float, default=0)
    x1: Mapped[float] = mapped_column(Float, default=0)
    y1: Mapped[float] = mapped_column(Float, default=0)
    is_included: Mapped[bool] = mapped_column(Boolean, default=True)

    page: Mapped[DocumentPage] = relationship(back_populates="blocks")
    sentences: Mapped[list[Sentence]] = relationship(
        back_populates="block", cascade="all, delete-orphan"
    )


class Sentence(Base):
    __tablename__ = "sentences"
    __table_args__ = (
        UniqueConstraint("question_set_id", "sentence_index"),
        Index("ix_sentence_hash", "normalized_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    question_set_id: Mapped[int] = mapped_column(
        ForeignKey("question_sets.id", ondelete="CASCADE"), index=True
    )
    block_id: Mapped[int] = mapped_column(
        ForeignKey("content_blocks.id", ondelete="CASCADE"), index=True
    )
    sentence_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    normalized_hash: Mapped[str] = mapped_column(String(64))
    content_type: Mapped[str] = mapped_column(String(32), index=True)
    section_name: Mapped[str] = mapped_column(String(64), default="unknown")

    block: Mapped[ContentBlock] = relationship(back_populates="sentences")


class WordOccurrence(Base):
    __tablename__ = "word_occurrences"
    __table_args__ = (
        Index("ix_occurrence_doc_lemma_pos", "question_set_id", "lemma", "pos"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    question_set_id: Mapped[int] = mapped_column(
        ForeignKey("question_sets.id", ondelete="CASCADE"), index=True
    )
    sentence_id: Mapped[int] = mapped_column(
        ForeignKey("sentences.id", ondelete="CASCADE"), index=True
    )
    lemma: Mapped[str] = mapped_column(String(80), index=True)
    pos: Mapped[str] = mapped_column(String(16), default="X")
    surface_form: Mapped[str] = mapped_column(String(100))
    char_start: Mapped[int] = mapped_column(Integer, default=0)
    char_end: Mapped[int] = mapped_column(Integer, default=0)
    content_type: Mapped[str] = mapped_column(String(32), index=True)


class WordStat(Base):
    __tablename__ = "word_stats"
    __table_args__ = (
        UniqueConstraint("question_set_id", "lemma", "pos"),
        Index("ix_word_stat_doc_frequency", "question_set_id", "study_frequency"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    question_set_id: Mapped[int] = mapped_column(
        ForeignKey("question_sets.id", ondelete="CASCADE"), index=True
    )
    lemma: Mapped[str] = mapped_column(String(80), index=True)
    pos: Mapped[str] = mapped_column(String(16), default="X")
    total_frequency: Mapped[int] = mapped_column(Integer, default=0)
    study_frequency: Mapped[int] = mapped_column(Integer, default=0)
    passage_frequency: Mapped[int] = mapped_column(Integer, default=0)
    question_frequency: Mapped[int] = mapped_column(Integer, default=0)


class UserVocab(Base):
    __tablename__ = "user_vocab"
    __table_args__ = (UniqueConstraint("lemma", "pos"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    lemma: Mapped[str] = mapped_column(String(80), index=True)
    pos: Mapped[str] = mapped_column(String(16), default="X")
    status: Mapped[str] = mapped_column(String(24), default="new", index=True)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    lapse_count: Mapped[int] = mapped_column(Integer, default=0)
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    ebbinghaus_stage: Mapped[int] = mapped_column(Integer, default=0)
    next_review_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ReviewEvent(Base):
    __tablename__ = "review_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_set_id: Mapped[int | None] = mapped_column(
        ForeignKey("question_sets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    lemma: Mapped[str] = mapped_column(String(80), index=True)
    pos: Mapped[str] = mapped_column(String(16), default="X")
    result: Mapped[str] = mapped_column(String(16))
    previous_status: Mapped[str] = mapped_column(String(24))
    next_status: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class SentenceTranslation(Base):
    __tablename__ = "sentence_translations"
    __table_args__ = (
        UniqueConstraint("sentence_hash", "model_name", "prompt_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sentence_hash: Mapped[str] = mapped_column(String(64), index=True)
    source_text: Mapped[str] = mapped_column(Text)
    translation: Mapped[str] = mapped_column(Text)
    model_name: Mapped[str] = mapped_column(String(128))
    prompt_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_set_id: Mapped[int] = mapped_column(
        ForeignKey("question_sets.id", ondelete="CASCADE"), index=True
    )
    job_type: Mapped[str] = mapped_column(String(32), default="parse")
    status: Mapped[str] = mapped_column(String(32), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    phase: Mapped[str] = mapped_column(String(64), default="等待处理")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ModelConfig(Base):
    __tablename__ = "model_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    base_url: Mapped[str] = mapped_column(Text)
    model_name: Mapped[str] = mapped_column(String(128))
    task_type: Mapped[str] = mapped_column(String(24), default="translation")
    temperature: Mapped[float] = mapped_column(Float, default=0.1)
    max_tokens: Mapped[int] = mapped_column(Integer, default=1024)
    enable_thinking: Mapped[bool] = mapped_column(Boolean, default=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    secret_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_test_status: Mapped[str] = mapped_column(String(24), default="untested")
    last_test_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class AIConversation(Base):
    __tablename__ = "ai_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_set_id: Mapped[int | None] = mapped_column(
        ForeignKey("question_sets.id", ondelete="SET NULL"), nullable=True
    )
    sentence_id: Mapped[int | None] = mapped_column(
        ForeignKey("sentences.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AIMessage(Base):
    __tablename__ = "ai_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("ai_conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

