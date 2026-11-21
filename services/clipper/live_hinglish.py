"""Compatibility wrapper for the shared IndicXlit Hinglish caption renderer."""
from __future__ import annotations

def romanize_text(text: str) -> str:
    """Use the bundled language-aware model while retaining English and punctuation."""
    from romanize import romanize_text as shared_romanize
    return shared_romanize(text)


def caption_words(words: list[dict]) -> list[dict]:
    """Return caption copies in natural model-ranked Hinglish transliteration."""
    from romanize import caption_words as shared_caption_words
    return shared_caption_words(words)
