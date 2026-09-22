from __future__ import annotations

import hashlib
import io
import re
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import distinct, func, select, text
from sqlalchemy.orm import Session

from .config import settings
from .database import Base, engine, get_db
from .models import (
    AIConversation,
    AIMessage,
    ContentBlock,
    DocumentPage,
    ModelConfig,
    ProcessingJob,
    QuestionSet,
    ReviewEvent,
    Sentence,
    SentenceTranslation,
    UserVocab,
    WordOccurrence,
    WordStat,
)
from .schemas import (
    BlockUpdate,
    ChatRequest,
    ModelConfigInput,
    ReviewAnswer,
    TranslateRequest,
    VocabStatusUpdate,
)
from .services.ai import (
    choose_model_config,
    completion,
    mark_test_result,
    test_model,
    translate_sentences,
    validate_base_url,
)
from .services.exporter import export_question_set
from .services.processor import process_question_set, rebuild_word_stats
from .services.secrets import delete_api_key, set_api_key
from .services.vocabulary import VocabEntry, get_vocabulary


def seed_defaults(session: Session) -> None:
    if session.scalar(select(func.count()).select_from(ModelConfig)):
        return
    session.add_all(
        [
            ModelConfig(
                name="千问快速翻译",
                base_url=(
                    "https://llm-fnv9qmq682nwjkjo.cn-beijing.maas.aliyuncs.com/"
                    "compatible-mode/v1"
                ),
                model_name="qwen3.7-flash",
                task_type="translation",
                temperature=0.1,
                max_tokens=2048,
                enable_thinking=False,
                is_default=True,
            ),
            ModelConfig(
                name="千问阅读助手",
                base_url=(
                    "https://llm-fnv9qmq682nwjkjo.cn-beijing.maas.aliyuncs.com/"
                    "compatible-mode/v1"
                ),
                model_name="qwen3.7-plus",
                task_type="chat",
                temperature=0.3,
                max_tokens=4096,
                enable_thinking=False,
                is_default=True,
            ),
        ]
    )
    session.commit()


# 艾宾浩斯记忆曲线：相邻两次复习的间隔天数，累计约 1/2/4/7/15/30 天
EBBINGHAUS_INTERVAL_DAYS = [1, 1, 2, 3, 8, 15]
# 每日任务的固定新词数量
DAILY_NEW_WORD_LIMIT = 20


def run_migrations() -> None:
    """为旧版本数据库补充新增列（create_all 不会修改已有表结构）。"""
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(user_vocab)"))}
        if "review_count" not in columns:
            conn.execute(
                text("ALTER TABLE user_vocab ADD COLUMN review_count INTEGER NOT NULL DEFAULT 0")
            )
        if "ebbinghaus_stage" not in columns:
            conn.execute(
                text("ALTER TABLE user_vocab ADD COLUMN ebbinghaus_stage INTEGER NOT NULL DEFAULT 0")
            )
        if "last_success_date" not in columns:
            conn.execute(
                text("ALTER TABLE user_vocab ADD COLUMN last_success_date TEXT")
            )
        # 掌握即毕业：清除历史遗留的已掌握词的曲线计划，避免到期后被每日任务召回
        conn.execute(
            text("UPDATE user_vocab SET next_review_at = NULL WHERE status = 'mastered'")
        )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(engine)
    run_migrations()
    with Session(engine) as session:
        seed_defaults(session)
    get_vocabulary()
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def entry_payload(entry: VocabEntry | None) -> dict:
    if not entry:
        return {
            "phonetic": "",
            "definition": "",
            "levels": [],
        }
    return {
        "phonetic": entry.phonetic,
        "definition": entry.chinese,
        "levels": entry.levels,
    }


def aggregate_vocab_status(statuses: list[str]) -> str:
    values = set(statuses)
    if "mastered" in values:
        return "mastered"
    if "learning" in values:
        return "learning"
    if values == {"suspended"}:
        return "suspended"
    return "new"


def document_payload(document: QuestionSet, session: Session) -> dict:
    block_counts = dict(
        session.execute(
            select(ContentBlock.content_type, func.count(ContentBlock.id))
            .join(DocumentPage, DocumentPage.id == ContentBlock.page_id)
            .where(DocumentPage.question_set_id == document.id)
            .group_by(ContentBlock.content_type)
        ).all()
    )
    mastered = session.scalar(
        select(func.count(distinct(WordStat.lemma)))
        .join(
            UserVocab,
            (UserVocab.lemma == WordStat.lemma) & (UserVocab.pos == WordStat.pos),
        )
        .where(
            WordStat.question_set_id == document.id,
            UserVocab.status == "mastered",
        )
    ) or 0
    vocab_count = session.scalar(
        select(func.count(distinct(WordStat.lemma))).where(
            WordStat.question_set_id == document.id
        )
    ) or 0
    return {
        "id": document.id,
        "filename": document.filename,
        "title": document.title,
        "status": document.status,
        "progress": document.progress,
        "current_phase": document.current_phase,
        "error_message": document.error_message,
        "page_count": document.page_count,
        "word_count": document.word_count,
        "vocab_count": vocab_count,
        "mastered_count": mastered,
        "block_counts": block_counts,
        "created_at": document.created_at.isoformat(),
        "parser_version": document.parser_version,
    }


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "app": settings.app_name}


@app.get("/api/overview")
def overview(session: Session = Depends(get_db)) -> dict:
    total_documents = session.scalar(select(func.count()).select_from(QuestionSet)) or 0
    completed_documents = session.scalar(
        select(func.count()).select_from(QuestionSet).where(QuestionSet.status == "done")
    ) or 0
    statuses_by_lemma: dict[str, list[str]] = defaultdict(list)
    for row in session.scalars(select(UserVocab)).all():
        statuses_by_lemma[row.lemma].append(row.status)
    aggregated_statuses = [
        aggregate_vocab_status(values) for values in statuses_by_lemma.values()
    ]
    mastered = aggregated_statuses.count("mastered")
    learning = aggregated_statuses.count("learning")
    review_events = session.scalar(select(func.count()).select_from(ReviewEvent)) or 0
    return {
        "total_documents": total_documents,
        "completed_documents": completed_documents,
        "mastered": mastered,
        "learning": learning,
        "review_events": review_events,
        "vocab_source": get_vocabulary().source,
        "vocab_version": get_vocabulary().version,
    }


@app.post("/api/upload")
async def upload_question_set(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    session: Session = Depends(get_db),
) -> dict:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".pdf", ".docx"}:
        raise HTTPException(400, "仅支持 PDF 和 DOCX 文件")
    content = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"文件不能超过 {settings.max_upload_mb} MB")
    file_hash = hashlib.sha256(content).hexdigest()
    existing = session.scalar(
        select(QuestionSet).where(QuestionSet.file_hash == file_hash)
    )
    if existing:
        payload = document_payload(existing, session)
        payload["duplicate"] = True
        return payload
    storage_path = settings.upload_dir / f"{uuid.uuid4().hex}{suffix}"
    storage_path.write_bytes(content)
    title = re.sub(r"\.(pdf|docx)$", "", file.filename or "未命名真题", flags=re.I)
    question_set = QuestionSet(
        filename=file.filename or storage_path.name,
        title=title,
        storage_path=str(storage_path),
        file_hash=file_hash,
        file_type=suffix.lstrip("."),
        status="queued",
        parser_version=settings.parser_version,
    )
    session.add(question_set)
    session.flush()
    session.add(ProcessingJob(question_set_id=question_set.id))
    session.commit()
    background_tasks.add_task(process_question_set, question_set.id)
    return document_payload(question_set, session)


@app.get("/api/question-sets")
def list_question_sets(session: Session = Depends(get_db)) -> list[dict]:
    documents = session.scalars(
        select(QuestionSet).order_by(QuestionSet.created_at.desc())
    ).all()
    return [document_payload(document, session) for document in documents]


@app.get("/api/question-sets/{question_set_id}")
def get_question_set(
    question_set_id: int, session: Session = Depends(get_db)
) -> dict:
    document = session.get(QuestionSet, question_set_id)
    if not document:
        raise HTTPException(404, "题目不存在")
    return document_payload(document, session)


@app.delete("/api/question-sets/{question_set_id}")
def delete_question_set(
    question_set_id: int, session: Session = Depends(get_db)
) -> dict:
    document = session.get(QuestionSet, question_set_id)
    if not document:
        raise HTTPException(404, "题目不存在")
    storage_path = Path(document.storage_path)
    session.delete(document)
    session.commit()
    storage_path.unlink(missing_ok=True)
    return {"deleted": True}


@app.post("/api/question-sets/{question_set_id}/reprocess")
def reprocess_question_set(
    question_set_id: int,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_db),
) -> dict:
    document = session.get(QuestionSet, question_set_id)
    if not document:
        raise HTTPException(404, "题目不存在")
    document.status = "queued"
    document.progress = 0
    document.current_phase = "等待重新解析"
    session.add(ProcessingJob(question_set_id=question_set_id))
    session.commit()
    background_tasks.add_task(process_question_set, question_set_id)
    return {"queued": True}


@app.get("/api/question-sets/{question_set_id}/blocks")
def list_blocks(
    question_set_id: int,
    page: int | None = None,
    session: Session = Depends(get_db),
) -> list[dict]:
    statement = (
        select(ContentBlock, DocumentPage.page_index)
        .join(DocumentPage, DocumentPage.id == ContentBlock.page_id)
        .where(DocumentPage.question_set_id == question_set_id)
        .order_by(DocumentPage.page_index, ContentBlock.block_index)
    )
    if page is not None:
        statement = statement.where(DocumentPage.page_index == page - 1)
    return [
        {
            "id": block.id,
            "page": page_index + 1,
            "content_type": block.content_type,
            "section_name": block.section_name,
            "text": block.text,
            "is_included": block.is_included,
            "bbox": [block.x0, block.y0, block.x1, block.y1],
        }
        for block, page_index in session.execute(statement).all()
    ]


@app.patch("/api/blocks/{block_id}")
def update_block(
    block_id: int, body: BlockUpdate, session: Session = Depends(get_db)
) -> dict:
    block = session.get(ContentBlock, block_id)
    if not block:
        raise HTTPException(404, "区块不存在")
    block.is_included = body.is_included
    session.commit()
    question_set_id = block.page.question_set_id
    rebuild_word_stats(question_set_id)
    return {"id": block.id, "is_included": block.is_included}


def _word_stats_rows(
    session: Session,
    question_set_id: int,
    scope: str,
    level: str,
    status: str,
    search: str,
    min_frequency: int = 0,
    review_filter: str = "all",
) -> list[dict]:
    vocab = get_vocabulary()
    stats = session.scalars(
        select(WordStat)
        .where(WordStat.question_set_id == question_set_id)
        .order_by(
            (WordStat.total_frequency if scope == "all" else WordStat.study_frequency).desc(),
            WordStat.lemma,
        )
    ).all()
    statuses_by_lemma: dict[str, list[str]] = defaultdict(list)
    reviews_by_lemma: dict[str, int] = defaultdict(int)
    for row in session.scalars(select(UserVocab)).all():
        statuses_by_lemma[row.lemma].append(row.status)
        reviews_by_lemma[row.lemma] += row.review_count or 0
    grouped: dict[str, dict] = {}
    for stat_row in stats:
        entry = vocab.get(stat_row.lemma)
        if not entry or not vocab.in_level(stat_row.lemma, level):
            continue
        if search and search.lower() not in stat_row.lemma.lower() and search not in entry.chinese:
            continue
        frequency = (
            stat_row.total_frequency if scope == "all" else stat_row.study_frequency
        )
        if frequency == 0:
            continue
        word = grouped.setdefault(
            stat_row.lemma,
            {
                "id": stat_row.id,
                "lemma": stat_row.lemma,
                "pos": stat_row.pos,
                "pos_values": [],
                "frequency": 0,
                "study_frequency": 0,
                "total_frequency": 0,
                "passage_frequency": 0,
                "question_frequency": 0,
                "review_count": reviews_by_lemma.get(stat_row.lemma, 0),
                "_primary_frequency": -1,
                **entry_payload(entry),
            },
        )
        word["pos_values"].append(stat_row.pos)
        word["frequency"] += frequency
        word["study_frequency"] += stat_row.study_frequency
        word["total_frequency"] += stat_row.total_frequency
        word["passage_frequency"] += stat_row.passage_frequency
        word["question_frequency"] += stat_row.question_frequency
        if frequency > word["_primary_frequency"]:
            word["id"] = stat_row.id
            word["pos"] = stat_row.pos
            word["_primary_frequency"] = frequency

    payload = []
    for word in grouped.values():
        word["pos_values"] = sorted(set(word["pos_values"]))
        word["pos_label"] = " · ".join(word["pos_values"])
        word["status"] = aggregate_vocab_status(
            statuses_by_lemma.get(word["lemma"], [])
        )
        word.pop("_primary_frequency", None)
        if word["frequency"] < min_frequency:
            continue
        if review_filter == "none" and word["review_count"] > 0:
            continue
        if review_filter == "min1" and word["review_count"] < 1:
            continue
        if review_filter == "min3" and word["review_count"] < 3:
            continue
        if review_filter == "min5" and word["review_count"] < 5:
            continue
        if status != "all" and word["status"] != status:
            continue
        payload.append(word)
    payload.sort(key=lambda row: (-row["frequency"], row["lemma"]))
    return payload


@app.get("/api/question-sets/{question_set_id}/word-stats")
def list_word_stats(
    question_set_id: int,
    scope: str = Query("study", pattern="^(study|all)$"),
    level: str = Query("cet6", pattern="^(cet6|cet4|all)$"),
    status: str = Query("all", pattern="^(all|new|learning|mastered|suspended)$"),
    search: str = "",
    min_frequency: int = Query(0, ge=0, le=999),
    review_filter: str = Query("all", pattern="^(all|none|min1|min3|min5)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=10, le=200),
    session: Session = Depends(get_db),
) -> dict:
    rows = _word_stats_rows(
        session,
        question_set_id,
        scope,
        level,
        status,
        search.strip(),
        min_frequency=min_frequency,
        review_filter=review_filter,
    )
    start = (page - 1) * page_size
    return {
        "items": rows[start : start + page_size],
        "total": len(rows),
        "page": page,
        "page_size": page_size,
    }


def examples_for_word(
    session: Session,
    question_set_id: int,
    lemma: str,
    pos: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    statement = (
        select(Sentence)
        .join(WordOccurrence, WordOccurrence.sentence_id == Sentence.id)
        .where(
            WordOccurrence.question_set_id == question_set_id,
            WordOccurrence.lemma == lemma,
        )
        .distinct()
        .order_by(Sentence.sentence_index)
    )
    if pos:
        statement = statement.where(WordOccurrence.pos == pos)
    if limit:
        statement = statement.limit(limit)
    sentences = session.scalars(statement).all()
    hashes = [sentence.normalized_hash for sentence in sentences]
    translations: dict[str, SentenceTranslation] = {}
    if hashes:
        for translation in session.scalars(
            select(SentenceTranslation)
            .where(SentenceTranslation.sentence_hash.in_(hashes))
            .order_by(SentenceTranslation.created_at.desc())
        ).all():
            translations.setdefault(translation.sentence_hash, translation)
    return [
        {
            "id": sentence.id,
            "text": sentence.text,
            "translation": translations.get(sentence.normalized_hash).translation
            if translations.get(sentence.normalized_hash)
            else None,
            "content_type": sentence.content_type,
            "section_name": sentence.section_name,
            "page": sentence.block.page.page_index + 1,
        }
        for sentence in sentences
    ]


@app.get("/api/word-stats/{word_stat_id}/examples")
def list_examples(word_stat_id: int, session: Session = Depends(get_db)) -> dict:
    stat_row = session.get(WordStat, word_stat_id)
    if not stat_row:
        raise HTTPException(404, "词条不存在")
    entry = get_vocabulary().get(stat_row.lemma)
    pos_values = sorted(
        set(
            session.scalars(
                select(WordStat.pos).where(
                    WordStat.question_set_id == stat_row.question_set_id,
                    WordStat.lemma == stat_row.lemma,
                )
            ).all()
        )
    )
    vocab_rows = session.scalars(
        select(UserVocab).where(UserVocab.lemma == stat_row.lemma)
    ).all()
    review_count = sum(row.review_count or 0 for row in vocab_rows)
    upcoming = [row.next_review_at for row in vocab_rows if row.next_review_at]
    return {
        "word": {
            "lemma": stat_row.lemma,
            "pos": stat_row.pos,
            "pos_values": pos_values,
            "pos_label": " · ".join(pos_values),
            "review_count": review_count,
            "next_review_at": min(upcoming).isoformat() if upcoming else None,
            **entry_payload(entry),
        },
        "examples": examples_for_word(
            session, stat_row.question_set_id, stat_row.lemma
        ),
    }


@app.get("/api/question-sets/{question_set_id}/study-queue")
def study_queue(
    question_set_id: int,
    level: str = Query("cet6", pattern="^(cet6|cet4|all)$"),
    order: str = Query("frequency", pattern="^(frequency|review_count)$"),
    mode: str = Query("free", pattern="^(free|daily)$"),
    scope: str = Query("study", pattern="^(study|all)$"),
    status: str = Query("all", pattern="^(all|new|learning|mastered|suspended)$"),
    search: str = "",
    min_frequency: int = Query(0, ge=0),
    review_filter: str = Query("all", pattern="^(all|none|min1|min3|min5)$"),
    session: Session = Depends(get_db),
) -> list[dict]:
    # 学习队列跟随词频表当前筛选（所见即所学）
    rows = _word_stats_rows(
        session, question_set_id, scope, level, status, search,
        min_frequency, review_filter,
    )

    def order_key(row: dict) -> tuple:
        if order == "review_count":
            return (-row["review_count"], -row["frequency"], row["lemma"])
        return (-row["frequency"], row["lemma"])

    if mode == "daily":
        now = datetime.utcnow()
        due_rows = session.execute(
            select(UserVocab.lemma, func.min(UserVocab.next_review_at))
            .where(
                UserVocab.next_review_at.is_not(None),
                UserVocab.next_review_at <= now,
            )
            .group_by(UserVocab.lemma)
        ).all()
        due_at = {lemma: earliest for lemma, earliest in due_rows}
        # 到期复习词：按记忆曲线最久到期优先，已忽略和已掌握的除外（掌握即毕业）
        due_words = [
            row
            for row in rows
            if row["lemma"] in due_at
            and row["status"] not in {"suspended", "mastered"}
        ]
        due_words.sort(key=lambda row: (due_at[row["lemma"]], row["lemma"]))
        # 固定 20 个新词，其余均为到期复习词
        new_words = [
            row
            for row in rows
            if row["status"] == "new" and row["lemma"] not in due_at
        ]
        new_words.sort(key=order_key)
        selected_rows = due_words + new_words[:DAILY_NEW_WORD_LIMIT]
    else:
        if status == "all":
            # 状态未筛选：默认跳过已掌握与已忽略
            selected_rows = [
                row for row in rows if row["status"] not in {"mastered", "suspended"}
            ]
        else:
            # 显式状态筛选：所见即所学（如筛选"已掌握"可重测）
            selected_rows = list(rows)
        selected_rows.sort(key=order_key)

    return [
        {
            **row,
            "examples": examples_for_word(
                session, question_set_id, row["lemma"], limit=3
            ),
        }
        for row in selected_rows
    ]


@app.put("/api/vocab/{lemma}/{pos}")
def set_vocab_status(
    lemma: str,
    pos: str,
    body: VocabStatusUpdate,
    session: Session = Depends(get_db),
) -> dict:
    row = session.scalar(
        select(UserVocab).where(UserVocab.lemma == lemma, UserVocab.pos == pos)
    )
    if not row:
        row = UserVocab(lemma=lemma, pos=pos)
        session.add(row)
    row.status = body.status
    if body.status == "new":
        row.success_count = 0
        row.next_review_at = None
        row.ebbinghaus_stage = 0
        row.last_success_date = None
    elif body.status == "mastered":
        # 手动标记掌握同样视为毕业，终止曲线计划
        row.next_review_at = None
    session.commit()
    return {"lemma": row.lemma, "pos": row.pos, "status": row.status}


@app.post("/api/reviews")
def record_review(body: ReviewAnswer, session: Session = Depends(get_db)) -> dict:
    row = session.scalar(
        select(UserVocab).where(
            UserVocab.lemma == body.lemma, UserVocab.pos == body.pos
        )
    )
    if not row:
        row = UserVocab(lemma=body.lemma, pos=body.pos)
        session.add(row)
        session.flush()
    previous = row.status
    now = datetime.utcnow()
    was_due = row.next_review_at is not None and row.next_review_at <= now
    row.review_count = (row.review_count or 0) + 1
    if body.known:
        # 当天重复认识只计 1 次：跨天累计 3 次才掌握
        today = datetime.now().date().isoformat()
        if row.last_success_date != today:
            row.success_count += 1
            row.last_success_date = today
        row.status = "mastered" if row.success_count >= 3 else "learning"
        if row.status == "mastered":
            # 掌握即毕业：曲线计划终止，不再安排后续复习
            row.next_review_at = None
        elif was_due:
            # 到期复习完成，进入下一阶段（间隔 1/1/2/3/8/15 天）
            row.ebbinghaus_stage += 1
            if row.ebbinghaus_stage >= len(EBBINGHAUS_INTERVAL_DAYS):
                row.next_review_at = None
            else:
                row.next_review_at = now + timedelta(
                    days=EBBINGHAUS_INTERVAL_DAYS[row.ebbinghaus_stage]
                )
        elif row.ebbinghaus_stage == 0 and row.next_review_at is None:
            # 首次学习，按记忆曲线安排第 1 天复习
            row.next_review_at = now + timedelta(days=EBBINGHAUS_INTERVAL_DAYS[0])
        # 未到期的额外练习不改变曲线计划
        result = "known"
    else:
        row.success_count = 0
        row.lapse_count += 1
        row.status = "learning"
        # 不认识：记忆曲线从头开始，次日再复习
        row.ebbinghaus_stage = 0
        row.next_review_at = now + timedelta(days=EBBINGHAUS_INTERVAL_DAYS[0])
        result = "unknown"
    session.add(
        ReviewEvent(
            question_set_id=body.question_set_id,
            lemma=body.lemma,
            pos=body.pos,
            result=result,
            previous_status=previous,
            next_status=row.status,
        )
    )
    session.commit()
    return {
        "lemma": row.lemma,
        "pos": row.pos,
        "status": row.status,
        "success_count": row.success_count,
        "lapse_count": row.lapse_count,
        "review_count": row.review_count,
        "ebbinghaus_stage": row.ebbinghaus_stage,
        "next_review_at": row.next_review_at.isoformat() if row.next_review_at else None,
    }


@app.get("/api/corpus/word-stats")
def corpus_word_stats(
    level: str = Query("cet6", pattern="^(cet6|cet4|all)$"),
    status: str = Query("all", pattern="^(all|new|learning|mastered|suspended)$"),
    search: str = "",
    min_frequency: int = Query(0, ge=0, le=999),
    review_filter: str = Query("all", pattern="^(all|none|min1|min3|min5)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=10, le=200),
    session: Session = Depends(get_db),
) -> dict:
    rows = session.execute(
        select(
            WordStat.lemma,
            func.sum(WordStat.total_frequency),
            func.sum(WordStat.study_frequency),
            func.count(distinct(WordStat.question_set_id)),
        )
        .group_by(WordStat.lemma)
        .order_by(func.sum(WordStat.study_frequency).desc())
    ).all()
    pos_values_by_lemma: dict[str, list[str]] = defaultdict(list)
    for lemma, pos in session.execute(select(WordStat.lemma, WordStat.pos).distinct()).all():
        pos_values_by_lemma[lemma].append(pos)
    statuses_by_lemma: dict[str, list[str]] = defaultdict(list)
    reviews_by_lemma: dict[str, int] = defaultdict(int)
    for row in session.scalars(select(UserVocab)).all():
        statuses_by_lemma[row.lemma].append(row.status)
        reviews_by_lemma[row.lemma] += row.review_count or 0
    vocab = get_vocabulary()
    payload = []
    for lemma, total_frequency, study_frequency, document_frequency in rows:
        entry = vocab.get(lemma)
        mastery = aggregate_vocab_status(statuses_by_lemma.get(lemma, []))
        review_count = reviews_by_lemma.get(lemma, 0)
        if not entry or not vocab.in_level(lemma, level):
            continue
        if status != "all" and mastery != status:
            continue
        if study_frequency < min_frequency:
            continue
        if review_filter == "none" and review_count > 0:
            continue
        if review_filter == "min1" and review_count < 1:
            continue
        if review_filter == "min3" and review_count < 3:
            continue
        if review_filter == "min5" and review_count < 5:
            continue
        if search and search.lower() not in lemma.lower() and search not in entry.chinese:
            continue
        payload.append(
            {
                "lemma": lemma,
                "pos_values": sorted(set(pos_values_by_lemma[lemma])),
                "pos_label": " · ".join(sorted(set(pos_values_by_lemma[lemma]))),
                "total_frequency": int(total_frequency or 0),
                "study_frequency": int(study_frequency or 0),
                "document_frequency": int(document_frequency or 0),
                "review_count": review_count,
                "status": mastery,
                **entry_payload(entry),
            }
        )
    start = (page - 1) * page_size
    return {
        "items": payload[start : start + page_size],
        "total": len(payload),
    }


@app.get("/api/corpus/word-stats/{lemma}/examples")
def corpus_examples(lemma: str, session: Session = Depends(get_db)) -> dict:
    lemma = lemma.strip().lower()
    entry = get_vocabulary().get(lemma)
    pos_values = sorted(
        set(
            session.scalars(
                select(WordStat.pos).where(WordStat.lemma == lemma)
            ).all()
        )
    )
    sentences = session.scalars(
        select(Sentence)
        .join(WordOccurrence, WordOccurrence.sentence_id == Sentence.id)
        .where(WordOccurrence.lemma == lemma)
        .distinct()
        .order_by(Sentence.question_set_id, Sentence.sentence_index)
    ).all()
    question_sets = {
        row.id: row.title
        for row in session.scalars(select(QuestionSet)).all()
    }
    hashes = [sentence.normalized_hash for sentence in sentences]
    translations: dict[str, SentenceTranslation] = {}
    if hashes:
        for translation in session.scalars(
            select(SentenceTranslation)
            .where(SentenceTranslation.sentence_hash.in_(hashes))
            .order_by(SentenceTranslation.created_at.desc())
        ).all():
            translations.setdefault(translation.sentence_hash, translation)
    vocab_rows = session.scalars(
        select(UserVocab).where(UserVocab.lemma == lemma)
    ).all()
    review_count = sum(row.review_count or 0 for row in vocab_rows)
    upcoming = [row.next_review_at for row in vocab_rows if row.next_review_at]
    return {
        "word": {
            "lemma": lemma,
            "pos_values": pos_values,
            "pos_label": " · ".join(pos_values),
            "review_count": review_count,
            "next_review_at": min(upcoming).isoformat() if upcoming else None,
            **entry_payload(entry),
        },
        "examples": [
            {
                "id": sentence.id,
                "text": sentence.text,
                "translation": translations.get(sentence.normalized_hash).translation
                if translations.get(sentence.normalized_hash)
                else None,
                "content_type": sentence.content_type,
                "section_name": sentence.section_name,
                "page": sentence.block.page.page_index + 1,
                "question_set_id": sentence.question_set_id,
                "question_set_title": question_sets.get(sentence.question_set_id, ""),
            }
            for sentence in sentences
        ],
    }


@app.get("/api/export/{question_set_id}")
def export_excel(question_set_id: int, session: Session = Depends(get_db)):
    try:
        buffer, filename = export_question_set(session, question_set_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    encoded = quote(filename)
    return StreamingResponse(
        buffer,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
    )


def model_payload(config: ModelConfig) -> dict:
    return {
        "id": config.id,
        "name": config.name,
        "base_url": config.base_url,
        "model_name": config.model_name,
        "task_type": config.task_type,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "enable_thinking": config.enable_thinking,
        "is_default": config.is_default,
        "has_api_key": bool(config.secret_ref),
        "last_test_status": config.last_test_status,
        "last_test_message": config.last_test_message,
        "last_tested_at": config.last_tested_at.isoformat()
        if config.last_tested_at
        else None,
    }


@app.get("/api/model-configs")
def list_model_configs(session: Session = Depends(get_db)) -> list[dict]:
    return [
        model_payload(config)
        for config in session.scalars(select(ModelConfig).order_by(ModelConfig.id)).all()
    ]


@app.post("/api/model-configs")
def create_model_config(
    body: ModelConfigInput, session: Session = Depends(get_db)
) -> dict:
    try:
        base_url = validate_base_url(str(body.base_url))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if body.is_default:
        session.query(ModelConfig).filter(
            ModelConfig.task_type.in_([body.task_type, "both"])
        ).update({ModelConfig.is_default: False}, synchronize_session=False)
    config = ModelConfig(
        name=body.name,
        base_url=base_url,
        model_name=body.model_name,
        task_type=body.task_type,
        temperature=body.temperature,
        max_tokens=body.max_tokens,
        enable_thinking=body.enable_thinking,
        is_default=body.is_default,
    )
    session.add(config)
    session.flush()
    if body.api_key:
        config.secret_ref = f"model-config-{config.id}"
        try:
            set_api_key(config.secret_ref, body.api_key)
        except Exception as exc:
            raise HTTPException(500, "无法写入系统钥匙串") from exc
    session.commit()
    return model_payload(config)


@app.put("/api/model-configs/{config_id}")
def update_model_config(
    config_id: int,
    body: ModelConfigInput,
    session: Session = Depends(get_db),
) -> dict:
    config = session.get(ModelConfig, config_id)
    if not config:
        raise HTTPException(404, "模型配置不存在")
    try:
        config.base_url = validate_base_url(str(body.base_url))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if body.is_default:
        session.query(ModelConfig).filter(
            ModelConfig.id != config_id,
            ModelConfig.task_type.in_([body.task_type, "both"]),
        ).update({ModelConfig.is_default: False}, synchronize_session=False)
    config.name = body.name
    config.model_name = body.model_name
    config.task_type = body.task_type
    config.temperature = body.temperature
    config.max_tokens = body.max_tokens
    config.enable_thinking = body.enable_thinking
    config.is_default = body.is_default
    if body.api_key:
        config.secret_ref = config.secret_ref or f"model-config-{config.id}"
        try:
            set_api_key(config.secret_ref, body.api_key)
        except Exception as exc:
            raise HTTPException(500, "无法写入系统钥匙串") from exc
    session.commit()
    return model_payload(config)


@app.delete("/api/model-configs/{config_id}")
def remove_model_config(
    config_id: int, session: Session = Depends(get_db)
) -> dict:
    config = session.get(ModelConfig, config_id)
    if not config:
        raise HTTPException(404, "模型配置不存在")
    delete_api_key(config.secret_ref)
    session.delete(config)
    session.commit()
    return {"deleted": True}


@app.post("/api/model-configs/{config_id}/test")
async def test_model_config(
    config_id: int, session: Session = Depends(get_db)
) -> dict:
    config = session.get(ModelConfig, config_id)
    if not config:
        raise HTTPException(404, "模型配置不存在")
    success, message = await test_model(config)
    mark_test_result(config, success, message)
    session.commit()
    return {"success": success, "message": message}


# 朗读：优先使用微软 Edge 神经网络语音（edge-tts，免费、无需 API key），磁盘缓存避免重复合成
try:
    import edge_tts
except ImportError:  # 未安装时接口返回 503，前端自动回退浏览器本地语音
    edge_tts = None

TTS_VOICE = "en-US-AvaNeural"  # 微软神经网络女声，自然度远超系统本地语音
TTS_CACHE_DIR = settings.data_dir / "tts_cache"
TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    rate: str = Field(default="+0%", pattern=r"^[+-]\d+%$")


@app.post("/api/tts")
async def tts(body: TTSRequest) -> Response:
    if edge_tts is None:
        raise HTTPException(503, "edge-tts 未安装，请执行 pip install edge-tts")
    cache_key = hashlib.sha256(
        f"{TTS_VOICE}|{body.rate}|{body.text}".encode()
    ).hexdigest()
    cache_file = TTS_CACHE_DIR / f"{cache_key}.mp3"
    if cache_file.exists():
        return Response(content=cache_file.read_bytes(), media_type="audio/mpeg")
    try:
        communicate = edge_tts.Communicate(
            text=body.text, voice=TTS_VOICE, rate=body.rate
        )
        audio = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio.write(chunk["data"])
        data = audio.getvalue()
    except Exception as exc:  # 网络异常等，前端会回退本地语音
        raise HTTPException(502, f"语音合成失败: {exc}") from exc
    if not data:
        raise HTTPException(502, "语音合成返回空音频")
    cache_file.write_bytes(data)
    return Response(content=data, media_type="audio/mpeg")


@app.post("/api/translate")
async def translate(
    body: TranslateRequest, session: Session = Depends(get_db)
) -> list[dict]:
    try:
        return await translate_sentences(
            session, body.sentence_ids, body.model_config_id
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/chat")
async def chat(body: ChatRequest, session: Session = Depends(get_db)) -> dict:
    try:
        config = choose_model_config(session, "chat", body.model_config_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    context_sentences: list[Sentence] = []
    current_sentence = session.get(Sentence, body.sentence_id) if body.sentence_id else None
    if current_sentence:
        context_sentences = session.scalars(
            select(Sentence)
            .where(
                Sentence.question_set_id == current_sentence.question_set_id,
                Sentence.section_name == current_sentence.section_name,
                Sentence.sentence_index.between(
                    current_sentence.sentence_index - 3,
                    current_sentence.sentence_index + 3,
                ),
            )
            .order_by(Sentence.sentence_index)
        ).all()
    conversation = (
        session.get(AIConversation, body.conversation_id)
        if body.conversation_id
        else None
    )
    if not conversation:
        conversation = AIConversation(
            question_set_id=body.question_set_id,
            sentence_id=body.sentence_id,
            title=body.message[:40],
        )
        session.add(conversation)
        session.flush()
    session.add(
        AIMessage(
            conversation_id=conversation.id, role="user", content=body.message
        )
    )
    history = session.scalars(
        select(AIMessage)
        .where(AIMessage.conversation_id == conversation.id)
        .order_by(AIMessage.id.desc())
        .limit(12)
    ).all()
    messages = [
        {
            "role": "system",
            "content": (
                "你是大学英语六级阅读老师。结合给定上下文回答语法、词汇、翻译和篇章问题。"
                "如果上下文不足，应明确说明，不要编造。"
            ),
        }
    ]
    if context_sentences:
        messages.append(
            {
                "role": "system",
                "content": "当前上下文：\n"
                + "\n".join(sentence.text for sentence in context_sentences),
            }
        )
    messages.extend(
        {"role": message.role, "content": message.content}
        for message in reversed(history)
    )
    try:
        reply = await completion(config, messages)
    except Exception as exc:
        session.rollback()
        raise HTTPException(400, str(exc)[:400]) from exc
    session.add(
        AIMessage(conversation_id=conversation.id, role="assistant", content=reply)
    )
    session.commit()
    return {"conversation_id": conversation.id, "reply": reply}


@app.get("/api/conversations")
def conversations(session: Session = Depends(get_db)) -> list[dict]:
    rows = session.scalars(
        select(AIConversation).order_by(AIConversation.created_at.desc())
    ).all()
    return [
        {
            "id": row.id,
            "title": row.title,
            "question_set_id": row.question_set_id,
            "sentence_id": row.sentence_id,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@app.get("/api/conversations/{conversation_id}/messages")
def conversation_messages(
    conversation_id: int, session: Session = Depends(get_db)
) -> list[dict]:
    return [
        {
            "id": row.id,
            "role": row.role,
            "content": row.content,
            "created_at": row.created_at.isoformat(),
        }
        for row in session.scalars(
            select(AIMessage)
            .where(AIMessage.conversation_id == conversation_id)
            .order_by(AIMessage.id)
        ).all()
    ]


frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
