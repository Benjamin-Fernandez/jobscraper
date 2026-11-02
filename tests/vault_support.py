"""An in-memory keyring for tests that reach `jobscraper.vault` (not a test file).

`memory_keyring()` swaps the keyring backend for one block and checks the swap took before
yielding, so a test can never write to the real Windows Credential Manager. The backend keeps
`.d` {(service, username): password} and `.calls` [(verb, service, username)] (never values).
"""
from __future__ import annotations

import contextlib


@contextlib.contextmanager
def memory_keyring():
    import keyring
    from keyring.backend import KeyringBackend
    from keyring.errors import PasswordDeleteError

    class Memory(KeyringBackend):
        priority = 1

        def __init__(self):
            super().__init__()
            self.d: dict[tuple[str, str], str] = {}
            self.calls: list[tuple[str, str, str]] = []

        def get_password(self, service, username):
            self.calls.append(("get", service, username))
            return self.d.get((service, username))

        def set_password(self, service, username, pw):
            self.calls.append(("set", service, username))
            self.d[(service, username)] = pw

        def delete_password(self, service, username):
            self.calls.append(("delete", service, username))
            if (service, username) not in self.d:
                raise PasswordDeleteError("none")
            del self.d[(service, username)]

    saved = keyring.get_keyring()
    mem = Memory()
    keyring.set_keyring(mem)
    if keyring.get_keyring() is not mem:
        keyring.set_keyring(saved)
        raise AssertionError("refusing to run against the real Credential Manager")
    try:
        yield mem
    finally:
        keyring.set_keyring(saved)
