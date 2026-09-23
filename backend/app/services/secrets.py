from __future__ import annotations

import os


def get_api_key() -> str | None:
    """密钥已改存数据库（model_configs.api_key）；此函数仅保留环境变量备用读取。"""
    return os.environ.get("CET6_API_KEY")
