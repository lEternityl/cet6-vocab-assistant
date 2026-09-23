from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import ModelConfig, Sentence, SentenceTranslation
from .secrets import get_api_key


def validate_base_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme == "https":
        return base_url.rstrip("/")
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}:
        return base_url.rstrip("/")
    raise ValueError("API 地址必须使用 HTTPS；本机模型可使用 localhost HTTP")


def choose_model_config(
    session: Session, task_type: str, config_id: int | None = None
) -> ModelConfig:
    if config_id:
        config = session.get(ModelConfig, config_id)
    else:
        config = session.scalars(
            select(ModelConfig)
            .where(
                ModelConfig.task_type.in_([task_type, "both"]),
                ModelConfig.is_default.is_(True),
            )
            .order_by(ModelConfig.id)
        ).first()
        if not config:
            config = session.scalars(
                select(ModelConfig)
                .where(ModelConfig.task_type.in_([task_type, "both"]))
                .order_by(ModelConfig.id)
            ).first()
    if not config:
        raise ValueError(f"尚未配置{task_type}模型")
    return config


async def completion(config: ModelConfig, messages: list[dict]) -> str:
    api_key = config.api_key or get_api_key()
    if not api_key:
        raise ValueError("未找到 API Key，请在设置中保存或设置 CET6_API_KEY")
    base_url = validate_base_url(config.base_url)
    body = {
        "model": config.model_name,
        "messages": messages,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "stream": False,
        "enable_thinking": config.enable_thinking,
    }
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=body,
        )
        response.raise_for_status()
        payload = response.json()
    return payload["choices"][0]["message"]["content"].strip()


async def test_model(config: ModelConfig) -> tuple[bool, str]:
    try:
        reply = await completion(
            config,
            [
                {"role": "system", "content": "Reply with exactly: OK"},
                {"role": "user", "content": "Connection test"},
            ],
        )
        return True, f"连接成功：{reply[:80]}"
    except Exception as exc:
        return False, str(exc)[:300]


def _parse_translation_json(content: str) -> dict[int, str]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
    payload = json.loads(cleaned)
    if isinstance(payload, dict):
        payload = payload.get("translations", [])
    return {
        int(item["id"]): str(item["translation"]).strip()
        for item in payload
        if item.get("translation")
    }


async def translate_sentences(
    session: Session,
    sentence_ids: list[int],
    config_id: int | None = None,
) -> list[dict]:
    config = choose_model_config(session, "translation", config_id)
    sentences = list(
        session.scalars(select(Sentence).where(Sentence.id.in_(sentence_ids))).all()
    )
    cached = {
        row.sentence_hash: row
        for row in session.scalars(
            select(SentenceTranslation).where(
                SentenceTranslation.sentence_hash.in_(
                    [sentence.normalized_hash for sentence in sentences]
                ),
                SentenceTranslation.model_name == config.model_name,
                SentenceTranslation.prompt_version == settings.prompt_version,
            )
        ).all()
    }
    missing = [s for s in sentences if s.normalized_hash not in cached]
    if missing:
        source = [{"id": sentence.id, "text": sentence.text} for sentence in missing]
        content = await completion(
            config,
            [
                {
                    "role": "system",
                    "content": (
                        "你是大学英语六级学习助手。将英文准确、自然地翻译为中文。"
                        "保持句义，不增加解释。只返回 JSON 数组，每项包含 id 和 translation。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(source, ensure_ascii=False),
                },
            ],
        )
        try:
            translated = _parse_translation_json(content)
        except Exception as exc:
            raise ValueError("模型返回格式无法解析，请重试或更换模型") from exc
        for sentence in missing:
            translation = translated.get(sentence.id)
            if not translation:
                continue
            row = SentenceTranslation(
                sentence_hash=sentence.normalized_hash,
                source_text=sentence.text,
                translation=translation,
                model_name=config.model_name,
                prompt_version=settings.prompt_version,
            )
            session.add(row)
            cached[sentence.normalized_hash] = row
        session.commit()
    return [
        {
            "sentence_id": sentence.id,
            "text": sentence.text,
            "translation": cached.get(sentence.normalized_hash).translation
            if cached.get(sentence.normalized_hash)
            else None,
            "model_name": config.model_name,
        }
        for sentence in sentences
    ]


def mark_test_result(config: ModelConfig, success: bool, message: str) -> None:
    config.last_test_status = "ok" if success else "error"
    config.last_test_message = message
    config.last_tested_at = datetime.utcnow()

