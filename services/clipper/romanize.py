"""Offline Hinglish rendering using the bundled AI4Bharat IndicXlit model."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import ctranslate2

DEVANAGARI = re.compile(r"[\u0900-\u0963\u0972-\u097f]+")


@lru_cache(maxsize=1)
def _translator() -> ctranslate2.Translator:
    model_dir = Path(__file__).resolve().parents[2] / "assets" / "indicxlit"
    if not (model_dir / "model.bin").is_file():
        # PyInstaller one-folder builds resolve packaged assets from _MEIPASS.
        import sys
        model_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2])) / "assets" / "indicxlit"
    if not (model_dir / "model.bin").is_file():
        raise FileNotFoundError(f"Offline Hinglish model is missing: {model_dir}")
    return ctranslate2.Translator(str(model_dir), device="cpu", compute_type="int8")


@lru_cache(maxsize=512)
def romanize_devanagari(text: str) -> str:
    """Return the top-ranked Roman-script result for one Devanagari segment."""
    chars = [char for char in text if not char.isspace()]
    if not chars:
        return text
    result = _translator().translate_batch(
        # This checkpoint expects an explicit Fairseq BOS even though the CT2
        # converter metadata disables automatic source BOS insertion.
        [["<s>", *chars]], target_prefix=[["__en__"]], beam_size=5,
    )[0].hypotheses
    if not result:
        raise RuntimeError("IndicXlit returned no transliteration candidate")
    rendered = "".join(token for token in result[0] if not token.startswith("__"))
    if not rendered or DEVANAGARI.search(rendered):
        raise RuntimeError("IndicXlit returned empty or non-Roman caption text")
    return rendered


def romanize_text(text: str) -> str:
    """Romanize Devanagari spans while leaving English and punctuation intact."""
    if not DEVANAGARI.search(text):
        return text
    return DEVANAGARI.sub(lambda match: romanize_devanagari(match.group(0)), text)


def caption_words(words: list[dict]) -> list[dict]:
    """Make caption word copies with Hindi in Latin script."""
    result = []
    for word in words:
        copied = dict(word)
        copied["w"] = romanize_text(str(word.get("w", "")))
        result.append(copied)
    return result
