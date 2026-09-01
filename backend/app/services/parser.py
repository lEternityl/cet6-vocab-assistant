from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf as fitz
from docx import Document

from .nlp import get_nlp


@dataclass(slots=True)
class ParsedBlock:
    index: int
    text: str
    content_type: str
    section_name: str
    bbox: tuple[float, float, float, float]
    included: bool


@dataclass(slots=True)
class ParsedPage:
    index: int
    width: float
    height: float
    raw_text: str
    blocks: list[ParsedBlock]


HEADER_FOOTER = re.compile(
    r"(?:试题册|大学英语六级考试|cet[- ]?6).*?(?:\d+)?$", re.IGNORECASE
)
QUESTION_LINE = re.compile(r"^(?:Questions?\s+\d+|\d{1,2}[.)]\s)", re.IGNORECASE)
OPTION_LINE = re.compile(r"^(?:[A-D][.)]\s|[A-D]\s+[A-Z])")
PART_MARKER = re.compile(r"Part\s+(I{1,4}|[1-4])\b", re.IGNORECASE)


def normalize_text(text: str) -> str:
    text = text.replace("\u00ad", "").replace("\u200b", "")
    text = text.replace("“", '"').replace("”", '"').replace("’", "'")
    text = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def update_section(text: str, current: str) -> str:
    lowered = text.lower()
    if "writing" in lowered and ("part i" in lowered or current == "unknown"):
        return "writing"
    if "listening comprehension" in lowered:
        return "listening"
    if "reading comprehension" in lowered:
        return "reading"
    if re.search(r"part\s+(?:iv|4)\b", lowered) or (
        "translation" in lowered and "directions" in lowered
    ):
        return "translation"
    return current


def classify_block(
    text: str,
    section: str,
    y0: float,
    y1: float,
    page_height: float,
) -> tuple[str, bool]:
    stripped = text.strip()
    lowered = stripped.lower()
    if y0 < 24 or y1 > page_height - 22 or HEADER_FOOTER.search(stripped):
        return "boilerplate", False
    if (
        lowered.startswith("directions")
        or "answer sheet" in lowered
        or PART_MARKER.fullmatch(stripped)
    ):
        return "instruction", False
    if QUESTION_LINE.match(stripped):
        return "question", True
    if OPTION_LINE.match(stripped):
        return "option", False
    if section == "reading":
        return "passage", True
    if section == "writing":
        return "writing", True
    if section == "translation":
        return "translation", True
    if section == "listening":
        return "listening", False
    return "unknown", False


def parse_pdf(path: Path) -> list[ParsedPage]:
    pages: list[ParsedPage] = []
    section = "unknown"
    with fitz.open(path) as document:
        for page_index, page in enumerate(document):
            raw_blocks = page.get_text("blocks", sort=True)
            parsed_blocks: list[ParsedBlock] = []
            raw_texts: list[str] = []
            for block_index, raw in enumerate(raw_blocks):
                x0, y0, x1, y1, text, *_ = raw
                text = normalize_text(text)
                if not text or not re.search(r"[A-Za-z]", text):
                    continue
                raw_texts.append(text)
                section = update_section(text, section)
                content_type, included = classify_block(
                    text, section, y0, y1, page.rect.height
                )
                parsed_blocks.append(
                    ParsedBlock(
                        index=block_index,
                        text=text,
                        content_type=content_type,
                        section_name=section,
                        bbox=(x0, y0, x1, y1),
                        included=included,
                    )
                )
            pages.append(
                ParsedPage(
                    index=page_index,
                    width=page.rect.width,
                    height=page.rect.height,
                    raw_text="\n".join(raw_texts),
                    blocks=parsed_blocks,
                )
            )
    return pages


def parse_docx(path: Path) -> list[ParsedPage]:
    document = Document(path)
    section = "unknown"
    blocks: list[ParsedBlock] = []
    for index, paragraph in enumerate(document.paragraphs):
        text = normalize_text(paragraph.text)
        if not text or not re.search(r"[A-Za-z]", text):
            continue
        section = update_section(text, section)
        content_type, included = classify_block(text, section, 0, 0, 1000)
        blocks.append(
            ParsedBlock(
                index=index,
                text=text,
                content_type=content_type,
                section_name=section,
                bbox=(0, 0, 0, 0),
                included=included,
            )
        )
    return [
        ParsedPage(
            index=0,
            width=0,
            height=0,
            raw_text="\n".join(block.text for block in blocks),
            blocks=blocks,
        )
    ]


def parse_document(path: Path) -> list[ParsedPage]:
    if path.suffix.lower() == ".pdf":
        return parse_pdf(path)
    if path.suffix.lower() == ".docx":
        return parse_docx(path)
    raise ValueError("仅支持 PDF 和 DOCX 文件")


def segment_block(text: str, content_type: str) -> list[str]:
    if content_type in {"option", "question", "instruction", "boilerplate"}:
        return [line.strip() for line in text.splitlines() if line.strip()]
    return get_nlp().sentences(text)


def text_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
