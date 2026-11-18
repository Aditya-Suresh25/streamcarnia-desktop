"""Thin secure-storage wrapper over the operating-system keyring."""
from __future__ import annotations


class CredentialVault:
    SERVICE = "StreamCarnia.LiveAutoClipper"

    def __init__(self, keyring_module=None):
        if keyring_module is None:
            import keyring as keyring_module
        self.keyring = keyring_module
        backend = self.keyring.get_keyring()
        if getattr(backend, "priority", 0) <= 0:
            raise RuntimeError("No secure operating-system credential store is available")

    def set(self, name: str, value: str) -> None:
        if not name or not value:
            raise ValueError("Credential name and value are required")
        self.keyring.set_password(self.SERVICE, name, value)

    def get(self, name: str) -> str | None:
        return self.keyring.get_password(self.SERVICE, name)

    def delete(self, name: str) -> None:
        try:
            self.keyring.delete_password(self.SERVICE, name)
        except self.keyring.errors.PasswordDeleteError:
            pass
