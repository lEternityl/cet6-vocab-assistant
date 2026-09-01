from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from sqlalchemy import delete, select

from ..config import settings
from ..database import SessionLocal
from ..models import (
    ContentBlock,
    DocumentPage,
    ProcessingJob,
    QuestionSet,
    Sentence,
    WordOccurrence,
    WordStat,
)
from .nlp import get_nlp
from .parser import parse_document, segment_block, text_hash


STUDY_TYPES = {"passage", "question", "writing", "translation"}


def _set_progress(session, question_set, job, value: int, phase: str) -> None:
    question_set.progress = value
    question_set.current_phase = phase
    job.progress = value
    job.phase = phase
    session.commit()


def process_question_set(question_set_id: int) -> None:
    with SessionLocal() as session:
        question_set = session.get(QuestionSet, question_set_id)
        if not question_set:
            return
        job = session.scalars(
            select(ProcessingJob)
            .where(ProcessingJob.question_set_id == question_set_id)
            .order_by(ProcessingJob.id.desc())
        ).first()
        if not job:
            job = ProcessingJob(question_set_id=question_set_id)
            session.add(job)
            session.flush()
        question_set.status = "processing"
        question_set.error_message = None
        job.status = "processing"
        session.commit()

        try:
            _set_progress(session, question_set, job, 8, "提取页面与版面区块")
            pages = parse_document(Path(question_set.storage_path))

            session.execute(
                delete(WordStat).where(WordStat.question_set_id == question_set_id)
            )
            session.execute(
                delete(WordOccurrence).where(
                    WordOccurrence.question_set_id == question_set_id
                )
            )
            session.execute(
                delete(Sentence).where(Sentence.question_set_id == question_set_id)
            )
            session.execute(
                delete(DocumentPage).where(
                    DocumentPage.question_set_id == question_set_id
                )
            )
            session.commit()

            _set_progress(session, question_set, job, 22, "识别文章、题干与固定说明")
            sentence_index = 0
            total_words = 0
            counters: dict[tuple[str, str], Counter] = defaultdict(Counter)
            all_text: list[str] = []
            nlp = get_nlp()

            for page_number, parsed_page in enumerate(pages, start=1):
                db_page = DocumentPage(
                    question_set_id=question_set_id,
                    page_index=parsed_page.index,
                    width=parsed_page.width,
                    height=parsed_page.height,
                    raw_text=parsed_page.raw_text,
                )
                session.add(db_page)
                session.flush()
                all_text.append(parsed_page.raw_text)
                for parsed_block in parsed_page.blocks:
                    x0, y0, x1, y1 = parsed_block.bbox
                    db_block = ContentBlock(
                        page_id=db_page.id,
                        block_index=parsed_block.index,
                        content_type=parsed_block.content_type,
                        section_name=parsed_block.section_name,
                        text=parsed_block.text,
                        x0=x0,
                        y0=y0,
                        x1=x1,
                        y1=y1,
                        is_included=parsed_block.included,
                    )
                    session.add(db_block)
                    session.flush()
                    for sentence_text in segment_block(
                        parsed_block.text, parsed_block.content_type
                    ):
                        if len(sentence_text) < 2:
                            continue
                        db_sentence = Sentence(
                            question_set_id=question_set_id,
                            block_id=db_block.id,
                            sentence_index=sentence_index,
                            text=sentence_text,
                            normalized_hash=text_hash(sentence_text),
                            content_type=parsed_block.content_type,
                            section_name=parsed_block.section_name,
                        )
                        session.add(db_sentence)
                        session.flush()
                        matches, word_count = nlp.analyze(sentence_text)
                        total_words += word_count
                        for match in matches:
                            session.add(
                                WordOccurrence(
                                    question_set_id=question_set_id,
                                    sentence_id=db_sentence.id,
                                    lemma=match.lemma,
                                    pos=match.pos,
                                    surface_form=match.surface,
                                    char_start=match.start,
                                    char_end=match.end,
                                    content_type=parsed_block.content_type,
                                )
                            )
                            counter = counters[(match.lemma, match.pos)]
                            counter["total"] += 1
                            if parsed_block.included:
                                counter["study"] += 1
                            if parsed_block.content_type == "passage":
                                counter["passage"] += 1
                            if parsed_block.content_type == "question":
                                counter["question"] += 1
                        sentence_index += 1
                progress = 22 + int(page_number / max(len(pages), 1) * 58)
                question_set.progress = progress
                job.progress = progress
                if page_number % 2 == 0:
                    session.commit()

            _set_progress(session, question_set, job, 86, "汇总词频与学习范围")
            for (lemma, pos), counter in counters.items():
                session.add(
                    WordStat(
                        question_set_id=question_set_id,
                        lemma=lemma,
                        pos=pos,
                        total_frequency=counter["total"],
                        study_frequency=counter["study"],
                        passage_frequency=counter["passage"],
                        question_frequency=counter["question"],
                    )
                )

            question_set.text_content = "\n\n".join(all_text)
            question_set.page_count = len(pages)
            question_set.word_count = total_words
            question_set.vocab_count = len(counters)
            question_set.status = "done"
            question_set.progress = 100
            question_set.current_phase = "解析完成"
            question_set.parser_version = settings.parser_version
            job.status = "done"
            job.progress = 100
            job.phase = "解析完成"
            session.commit()
        except Exception as exc:
            session.rollback()
            question_set = session.get(QuestionSet, question_set_id)
            job = session.scalars(
                select(ProcessingJob)
                .where(ProcessingJob.question_set_id == question_set_id)
                .order_by(ProcessingJob.id.desc())
            ).first()
            if question_set:
                question_set.status = "error"
                question_set.current_phase = "解析失败"
                question_set.error_message = str(exc)[:2000]
            if job:
                job.status = "error"
                job.phase = "解析失败"
                job.error_message = str(exc)[:2000]
            session.commit()


def rebuild_word_stats(question_set_id: int) -> None:
    with SessionLocal() as session:
        session.execute(
            delete(WordStat).where(WordStat.question_set_id == question_set_id)
        )
        rows = session.execute(
            select(
                WordOccurrence.lemma,
                WordOccurrence.pos,
                WordOccurrence.content_type,
                ContentBlock.is_included,
            )
            .join(Sentence, Sentence.id == WordOccurrence.sentence_id)
            .join(ContentBlock, ContentBlock.id == Sentence.block_id)
            .where(WordOccurrence.question_set_id == question_set_id)
        ).all()
        counters: dict[tuple[str, str], Counter] = defaultdict(Counter)
        for lemma, pos, content_type, included in rows:
            counter = counters[(lemma, pos)]
            counter["total"] += 1
            if included:
                counter["study"] += 1
            if content_type == "passage":
                counter["passage"] += 1
            if content_type == "question":
                counter["question"] += 1
        for (lemma, pos), counter in counters.items():
            session.add(
                WordStat(
                    question_set_id=question_set_id,
                    lemma=lemma,
                    pos=pos,
                    total_frequency=counter["total"],
                    study_frequency=counter["study"],
                    passage_frequency=counter["passage"],
                    question_frequency=counter["question"],
                )
            )
        question_set = session.get(QuestionSet, question_set_id)
        if question_set:
            question_set.vocab_count = len(counters)
        session.commit()

