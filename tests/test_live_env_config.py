import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.live_clipper.config import LiveClipperSettings
from services.live_clipper.env_config import env_value, parse_env_file
from services.live_clipper.secrets import CredentialVault


class FakeKeyring:
    class errors:
        class PasswordDeleteError(Exception):
            pass

    class Backend:
        priority = 1

    def __init__(self):
        self.values = {}

    def get_keyring(self):
        return self.Backend()

    def get_password(self, service, key):
        return self.values.get((service, key))

    def set_password(self, service, key, value):
        self.values[(service, key)] = value

    def delete_password(self, service, key):
        self.values.pop((service, key), None)


class EnvConfigTests(unittest.TestCase):
    def test_env_parser_handles_comments_quotes_and_windows_paths(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / ".env"
            path.write_text(
                '# local settings\nGEMINI_API_KEY="AIza-example-key"\n'
                'GOOGLE_OAUTH_CLIENT_FILE="C:\\Users\\Me\\client_secret.json"\n'
                'UNRELATED=value\n', encoding="utf-8")
            parsed = parse_env_file(path)
            self.assertEqual(parsed["GEMINI_API_KEY"], "AIza-example-key")
            self.assertEqual(parsed["GOOGLE_OAUTH_CLIENT_FILE"], r"C:\Users\Me\client_secret.json")
            self.assertNotIn("UNRELATED", parsed)

    def test_process_environment_overrides_env_file_and_placeholders_are_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / ".env"
            path.write_text("GEMINI_API_KEY=replace_me\n", encoding="utf-8")
            with patch.dict(os.environ, {"GEMINI_API_KEY": "from-process"}):
                self.assertEqual(env_value("GEMINI_API_KEY", path), "from-process")
            with patch.dict(os.environ, {}, clear=True):
                self.assertIsNone(env_value("GEMINI_API_KEY", path))

    def test_vault_uses_secure_value_first_then_env_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / ".env"
            path.write_text("GEMINI_API_KEY=from-env\n", encoding="utf-8")
            keyring = FakeKeyring()
            vault = CredentialVault(keyring, env_path=path)
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(vault.get("gemini.api_key"), "from-env")
                vault.set("gemini.api_key", "from-keyring")
                self.assertEqual(vault.get("gemini.api_key"), "from-keyring")

    def test_live_settings_reads_oauth_client_path_from_env(self):
        with tempfile.TemporaryDirectory() as td:
            env_path = Path(td) / ".env"
            env_path.write_text("GOOGLE_OAUTH_CLIENT_FILE=C:\\Google\\desktop.json\n", encoding="utf-8")
            settings_path = Path(td) / "live.json"
            settings = LiveClipperSettings(settings_path)
            with patch.dict(os.environ, {}, clear=True), patch("services.live_clipper.config.live_env_value",
                       side_effect=lambda key: env_value(
                           "GOOGLE_OAUTH_CLIENT_FILE" if key == "oauth_client_file" else "GEMINI_API_KEY", env_path)):
                self.assertEqual(settings.get().oauth_client_file, r"C:\Google\desktop.json")


if __name__ == "__main__":
    unittest.main()
