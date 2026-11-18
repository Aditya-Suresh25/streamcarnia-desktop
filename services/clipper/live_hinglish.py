"""Hindi Devanagari to readable Latin-script captions for live clips only."""
from __future__ import annotations

import re


DEVANAGARI = re.compile(r"[\u0900-\u0963\u0972-\u097f]+")

VOWELS = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo",
    "ऋ": "ri", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au",
}
MATRA = {
    "ा": "aa", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo", "ृ": "ri",
    "े": "e", "ै": "ai", "ो": "o", "ौ": "au",
}
CONSONANTS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "ng",
    "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "ny",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "व": "v", "श": "sh",
    "ष": "sh", "स": "s", "ह": "h", "ळ": "l",
    "क़": "q", "ख़": "kh", "ग़": "gh", "ज़": "z", "ड़": "r",
    "ढ़": "rh", "फ़": "f", "ऱ": "r",
}
NUKTA_FORMS = {"क": "क़", "ख": "ख़", "ग": "ग़", "ज": "ज़", "ड": "ड़",
               "ढ": "ढ़", "फ": "फ़", "र": "ऱ"}
VIRAMA = "्"
NUKTA = "़"


def _romanize_word(word: str) -> str:
    output: list[str] = []
    index = 0
    final_inherent_vowel = False
    while index < len(word):
        char = word[index]
        final_inherent_vowel = False
        if char in CONSONANTS:
            if index + 1 < len(word) and word[index + 1] == NUKTA:
                char = NUKTA_FORMS.get(char, char)
                index += 1
            output.append(CONSONANTS[char])
            if index + 1 < len(word) and word[index + 1] in MATRA:
                output.append(MATRA[word[index + 1]])
                index += 1
            elif index + 1 < len(word) and word[index + 1] == VIRAMA:
                index += 1
            else:
                output.append("a")
                final_inherent_vowel = True
        elif char in VOWELS:
            output.append(VOWELS[char])
        elif char in {"ं", "ँ"}:
            output.append("n")
        elif char == "ः":
            output.append("h")
        else:
            # Keep punctuation, digits and unrecognized marks intact.
            output.append(char)
        index += 1

    # In ordinary Hindi, an inherent final schwa is usually not pronounced.
    if final_inherent_vowel and output and output[-1] == "a":
        output.pop()
    return "".join(output)


def romanize_text(text: str) -> str:
    """Transliterate Devanagari spans, retaining English and punctuation."""
    return DEVANAGARI.sub(lambda match: _romanize_word(match.group(0)), text)


def caption_words(words: list[dict]) -> list[dict]:
    """Return caption copies in Hinglish without modifying source transcript."""
    result = []
    for word in words:
        copied = dict(word)
        copied["w"] = romanize_text(str(word.get("w", "")))
        result.append(copied)
    return result
