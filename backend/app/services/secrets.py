from __future__ import annotations

import json
import logging
import os

import keyring

from ..config import settings

SERVICE_NAME = "cet6-vocab-assistant"
logger = logging.getLogger(__name__)

# 服务器等无桌面钥匙串的环境：回退到 data_dir 下的 JSON 文件（权限 600）
_FALLBACK_FILE = settings.data_dir / "secrets.json"


def _fallback_load() -> dict:
    try:
        return json.loads(_FALLBACK_FILE.read_text())
    except Exception:
        return {}


def _fallback_save(secrets: dict) -> None:
    _FALLBACK_FILE.write_text(json.dumps(secrets, ensure_ascii=False, indent=2))
    try:
        os.chmod(_FALLBACK_FILE, 0o600)
    except OSError:
        pass


def set_api_key(secret_ref: str, api_key: str) -> None:
    try:
        keyring.set_password(SERVICE_NAME, secret_ref, api_key)
        return
    except Exception as exc:
        logger.warning("keyring 不可用，密钥改存文件: %s", exc)
    secrets = _fallback_load()
    secrets[secret_ref] = api_key
    _fallback_save(secrets)


def get_api_key(secret_ref: str | None) -> str | None:
    if secret_ref:
        try:
            stored = keyring.get_password(SERVICE_NAME, secret_ref)
            if stored:
                return stored
        except Exception:
            pass
        stored = _fallback_load().get(secret_ref)
        if stored:
            return stored
    return os.environ.get("CET6_API_KEY")


def delete_api_key(secret_ref: str | None) -> None:
    if not secret_ref:
        return
    try:
        keyring.delete_password(SERVICE_NAME, secret_ref)
    except Exception:
        pass
    secrets = _fallback_load()
    if secrets.pop(secret_ref, None) is not None:
        _fallback_save(secrets)
