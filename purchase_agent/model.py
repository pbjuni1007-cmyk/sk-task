"""사용자가 허용한 프로젝트 자격 증명을 기록하거나 복사하지 않고 불러온다."""

import os
from pathlib import Path

from dotenv import dotenv_values
from langchain_openai import ChatOpenAI

ROOT = Path(__file__).resolve().parents[1]


def model_settings():
    values = dotenv_values(ROOT / ".env")
    return {
        "api_key": values.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY"),
        "model": values.get("PURCHASE_MODEL") or os.environ.get("PURCHASE_MODEL", "gpt-4o-mini"),
    }


def model_available():
    return bool(model_settings()["api_key"])


def make_model():
    settings = model_settings()
    if not settings["api_key"]:
        raise ValueError("MODEL_KEY_MISSING")
    # 추적이나 SDK의 암묵적 재시도를 사용하지 않는다. 호출 시도 횟수는 에이전트가 센다.
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    return ChatOpenAI(
        **settings,
        base_url="https://api.openai.com/v1",
        temperature=0,
        timeout=20,
        max_retries=0,
        stream_usage=True,
    )


def make_secondary_model():
    """사용자가 허용한 선택적 보조 자격 증명이며, 설정이나 로그에 절대 노출하지 않는다."""
    values = dotenv_values(ROOT / ".env")
    key = values.get("OPENAI_API_KEY_SUB") or os.environ.get("OPENAI_API_KEY_SUB")
    if not key or key == model_settings()["api_key"]:
        return None
    return ChatOpenAI(
        api_key=key,
        model=model_settings()["model"],
        base_url="https://api.openai.com/v1",
        temperature=0,
        timeout=20,
        max_retries=0,
        stream_usage=True,
    )
