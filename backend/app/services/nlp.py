from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

import spacy

from .vocabulary import VocabEntry, get_vocabulary


IRREGULAR = {
    "was": "be",
    "were": "be",
    "been": "be",
    "had": "have",
    "did": "do",
    "done": "do",
    "went": "go",
    "gone": "go",
    "grew": "grow",
    "grown": "grow",
    "brought": "bring",
    "thought": "think",
    "taught": "teach",
    "children": "child",
    "mice": "mouse",
    "men": "man",
    "women": "woman",
    "better": "good",
    "best": "good",
}


@dataclass(slots=True)
class TokenMatch:
    surface: str
    lemma: str
    pos: str
    start: int
    end: int
    entry: VocabEntry


def fallback_lemma(word: str) -> str:
    word = word.lower()
    vocab = get_vocabulary()
    if word in vocab.form_to_lemma:
        return vocab.form_to_lemma[word]
    if word in IRREGULAR:
        return IRREGULAR[word]
    if len(word) > 5 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 5 and word.endswith("ing"):
        stem = word[:-3]
        if len(stem) > 2 and stem[-1] == stem[-2]:
            stem = stem[:-1]
        if stem + "e" in vocab.entries:
            return stem + "e"
        return stem
    if len(word) > 4 and word.endswith("ed"):
        stem = word[:-2]
        if stem + "e" in vocab.entries:
            return stem + "e"
        if len(stem) > 2 and stem[-1] == stem[-2]:
            stem = stem[:-1]
        return stem
    if len(word) > 4 and word.endswith("es") and word[:-2] in vocab.entries:
        return word[:-2]
    if len(word) > 3 and word.endswith("s"):
        return word[:-1]
    return word


def fallback_pos(word: str, entry: VocabEntry) -> str:
    lowered = word.lower()
    if lowered.endswith("ly"):
        return "ADV"
    if lowered.endswith(("tion", "sion", "ment", "ness", "ity", "ance", "ence")):
        return "NOUN"
    if lowered.endswith(("ive", "ous", "ful", "less", "able", "ible", "al", "ic")):
        return "ADJ"
    if lowered.endswith(("ing", "ed", "ise", "ize", "ify")):
        return "VERB"
    return entry.primary_pos


class NLPProcessor:
    def __init__(self) -> None:
        try:
            self.nlp = spacy.load("en_core_web_sm", disable=["ner"])
            self.has_tagger = True
        except OSError:
            self.nlp = spacy.blank("en")
            self.has_tagger = False
        if "sentencizer" not in self.nlp.pipe_names and "parser" not in self.nlp.pipe_names:
            self.nlp.add_pipe("sentencizer")

    def sentences(self, text: str) -> list[str]:
        text = text.strip()
        if not text:
            return []
        if len(text) > 20000:
            chunks = re.split(r"(?<=[.!?])\s+", text)
            return [chunk.strip() for chunk in chunks if chunk.strip()]
        return [sent.text.strip() for sent in self.nlp(text).sents if sent.text.strip()]

    def analyze(self, text: str) -> tuple[list[TokenMatch], int]:
        doc = self.nlp(text)
        vocab = get_vocabulary()
        matches: list[TokenMatch] = []
        alphabetic_count = 0
        for token in doc:
            if not token.is_alpha or len(token.text) < 2:
                continue
            alphabetic_count += 1
            if token.pos_ == "PROPN" or (
                not self.has_tagger and token.idx > 0 and token.text[:1].isupper()
            ):
                continue
            raw_lemma = token.lemma_.lower() if self.has_tagger and token.lemma_ else ""
            lemma = raw_lemma if raw_lemma and raw_lemma != "-pron-" else fallback_lemma(token.text)
            entry = vocab.match(token.text, lemma)
            if not entry:
                continue
            pos = token.pos_ if self.has_tagger and token.pos_ else fallback_pos(token.text, entry)
            matches.append(
                TokenMatch(
                    surface=token.text,
                    lemma=entry.word.lower(),
                    pos=pos or "X",
                    start=token.idx,
                    end=token.idx + len(token.text),
                    entry=entry,
                )
            )
        return matches, alphabetic_count


@lru_cache(maxsize=1)
def get_nlp() -> NLPProcessor:
    return NLPProcessor()
