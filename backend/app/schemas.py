from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class BlockUpdate(BaseModel):
    is_included: bool


class VocabStatusUpdate(BaseModel):
    status: Literal["new", "learning", "mastered", "suspended"]


class ReviewAnswer(BaseModel):
    question_set_id: int | None = None
    lemma: str = Field(min_length=1, max_length=80)
    pos: str = Field(default="X", max_length=16)
    known: bool


class ModelConfigInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    base_url: HttpUrl
    model_name: str = Field(min_length=1, max_length=128)
    task_type: Literal["translation", "chat", "both"] = "translation"
    temperature: float = Field(default=0.1, ge=0, le=2)
    max_tokens: int = Field(default=1024, ge=64, le=65536)
    enable_thinking: bool = False
    is_default: bool = False
    api_key: str | None = Field(default=None, min_length=8)


class TranslateRequest(BaseModel):
    sentence_ids: list[int] = Field(min_length=1, max_length=20)
    model_config_id: int | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    question_set_id: int | None = None
    sentence_id: int | None = None
    conversation_id: int | None = None
    model_config_id: int | None = None

