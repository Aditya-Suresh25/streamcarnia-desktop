import unittest
import sys
import types
from unittest.mock import patch

from services.clipper.live_hinglish import caption_words, romanize_text


class LiveHinglishTests(unittest.TestCase):
    def test_common_hindi_words_are_transliterated_without_losing_initial_sounds(self):
        fake = types.ModuleType("romanize")
        fake.romanize_text = lambda text: text.replace("नमस्ते", "namaste")
        with patch.dict(sys.modules, {"romanize": fake}):
            self.assertEqual(romanize_text("नमस्ते gamer"), "namaste gamer")

    def test_english_and_punctuation_are_preserved(self):
        fake = types.ModuleType("romanize")
        fake.romanize_text = lambda text: text.replace("नमस्ते", "namaste")
        with patch.dict(sys.modules, {"romanize": fake}):
            self.assertEqual(romanize_text("नमस्ते, gamer!"), "namaste, gamer!")

    def test_caption_conversion_does_not_change_source_words_or_timing(self):
        source = [{"w": "ये", "s": 1.25, "e": 1.6}]
        fake = types.ModuleType("romanize")
        fake.caption_words = lambda words: [{**words[0], "w": "ye"}]
        with patch.dict(sys.modules, {"romanize": fake}):
            rendered = caption_words(source)
        self.assertEqual(rendered, [{"w": "ye", "s": 1.25, "e": 1.6}])
        self.assertEqual(source[0]["w"], "ये")


if __name__ == "__main__":
    unittest.main()
