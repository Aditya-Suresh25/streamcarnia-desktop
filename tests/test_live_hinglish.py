import unittest

from services.clipper.live_hinglish import caption_words, romanize_text


class LiveHinglishTests(unittest.TestCase):
    def test_common_hindi_words_are_transliterated_without_losing_initial_sounds(self):
        self.assertEqual(romanize_text("ये नमस्ते लुसिया क्यों हिंदी"),
                         "ye namaste lusiyaa kyon hindee")

    def test_english_and_punctuation_are_preserved(self):
        self.assertEqual(romanize_text("नमस्ते, gamer!"), "namaste, gamer!")

    def test_caption_conversion_does_not_change_source_words_or_timing(self):
        source = [{"w": "ये", "s": 1.25, "e": 1.6}]
        rendered = caption_words(source)
        self.assertEqual(rendered, [{"w": "ye", "s": 1.25, "e": 1.6}])
        self.assertEqual(source[0]["w"], "ये")


if __name__ == "__main__":
    unittest.main()
