from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


POS_MAP = {
    "n": "NOUN",
    "v": "VERB",
    "j": "ADJ",
    "a": "ADJ",
    "r": "ADV",
    "p": "ADP",
    "c": "CCONJ",
    "m": "NUM",
}


@dataclass(slots=True)
class VocabEntry:
    word: str
    levels: list[str]
    phonetic: str
    translation: list[str]
    definition: list[str]
    pos: list[str]
    exchange: list[str]

    @property
    def primary_pos(self) -> str:
        if not self.pos:
            return "X"
        ranked = sorted(
            self.pos,
            key=lambda value: int(value.split(":", 1)[1]) if ":" in value else 0,
            reverse=True,
        )
        return POS_MAP.get(ranked[0].split(":", 1)[0], "X")

    @property
    def chinese(self) -> str:
        return "；".join(self.translation[:4])


class VocabularyRepository:
    def __init__(self) -> None:
        data_path = Path(__file__).resolve().parents[1] / "data" / "vocab.json"
        payload = json.loads(data_path.read_text(encoding="utf-8"))
        self.version = payload["version"]
        self.source = payload["source"]
        self.entries: dict[str, VocabEntry] = {}
        self.form_to_lemma: dict[str, str] = {}
        for raw in payload["entries"]:
            entry = VocabEntry(**raw)
            key = entry.word.lower()
            self.entries[key] = entry
            self.form_to_lemma[key] = key
            for exchange in entry.exchange:
                if ":" not in exchange:
                    continue
                _, form = exchange.split(":", 1)
                for variant in re.split(r"[,;]", form):
                    variant = variant.strip().lower()
                    if variant and " " not in variant:
                        self.form_to_lemma.setdefault(variant, key)

    def get(self, word: str) -> VocabEntry | None:
        lemma = self.form_to_lemma.get(word.lower(), word.lower())
        return self.entries.get(lemma)

    def match(self, surface: str, proposed_lemma: str = "") -> VocabEntry | None:
        for candidate in (proposed_lemma, surface):
            candidate = candidate.strip().lower()
            if not candidate:
                continue
            mapped = self.form_to_lemma.get(candidate, candidate)
            if mapped in self.entries:
                return self.entries[mapped]
        return None

    def in_level(self, word: str, level: str) -> bool:
        entry = self.get(word)
        if not entry:
            return False
        return level == "all" or level in entry.levels


@lru_cache(maxsize=1)
def get_vocabulary() -> VocabularyRepository:
    return VocabularyRepository()

