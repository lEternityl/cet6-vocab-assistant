from __future__ import annotations

import os

import keyring


SERVICE_NAME = "cet6-vocab-assistant"


def set_api_key(secret_ref: str, api_key: str) -> None:
    keyring.set_password(SERVICE_NAME, secret_ref, api_key)


def get_api_key(secret_ref: str | None) -> str | None:
    if secret_ref:
        try:
            stored = keyring.get_password(SERVICE_NAME, secret_ref)
            if stored:
                return stored
        except Exception:
            pass
    return os.environ.get("CET6_API_KEY")


def delete_api_key(secret_ref: str | None) -> None:
    if not secret_ref:
        return
    try:
        keyring.delete_password(SERVICE_NAME, secret_ref)
    except Exception:
        pass

