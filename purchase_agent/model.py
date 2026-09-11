"""Load the user-authorized project credential without logging or copying it."""

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
    # No tracing or implicit SDK retries: call attempts are counted by the agent.
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
    """Optional user-authorized backup; never expose it in settings or logs."""
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
