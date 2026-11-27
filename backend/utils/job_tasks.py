"""Serializable job task handlers for Redis/RQ and memory backends."""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("careerai.jobs")


def run_career_coach(payload: dict) -> dict:
    from utils.mock_data import mock_career_coach_chat
    from utils.career_coach import career_coach_chat
    from utils.knowledge_base import build_knowledge_base
    from utils.openai_errors import format_openai_error
    from utils.session_store import save_json
    from utils.rag import UserKnowledgeBase

    message = payload["message"]
    upload_folder = payload["upload_folder"]
    store_id = payload["store_id"]
    session_data = payload.get("session_data") or {}
    user_id = payload.get("user_id")
    demo_mode = payload.get("demo_mode", True)
    chat_history = payload.get("chat_history") or []

    # Rebuild KB from serializable session snapshot (+ blob store_id when present)
    kb = build_knowledge_base(
        session_data, upload_folder, user_id=user_id, store_id=store_id
    )
    retrieved = kb.retrieve(message, top_k=6)
    api_error = None
    try:
        if demo_mode:
            reply, sources, retrieved_out = mock_career_coach_chat(message, kb, retrieved)
        else:
            from openai import OpenAI
            from utils.llm_config import GROQ_BASE_URL

            api_key = os.getenv("GROQ_API_KEY") or os.getenv("GROQ_KEY")
            client = OpenAI(api_key=api_key, base_url=GROQ_BASE_URL) if api_key else None
            reply, sources, retrieved_out = career_coach_chat(
                client, message, chat_history, kb
            )
    except Exception as exc:
        logger.exception("career_coach job failed")
        api_error = format_openai_error(exc)
        reply = f"I couldn't generate a response. {api_error}"
        sources = []
        retrieved_out = retrieved or []

    turn = {"user": message, "assistant": reply, "sources": sources}
    updated = (chat_history + [turn])[-6:]
    save_json(upload_folder, "coach_chat", updated, store_id=store_id)
    return {
        "reply": reply,
        "sources": sources,
        "retrieved": [
            {"label": r["label"], "text": r["text"][:200]} for r in retrieved_out[:3]
        ],
        "error": api_error,
    }


def run_cover_letter(payload: dict) -> dict:
    from utils.cover_letter import generate_cover_letter, mock_cover_letter
    from utils.openai_errors import format_openai_error
    from utils.session_store import save_json

    resume_text = payload["resume_text"]
    jd_text = payload["jd_text"]
    tone = payload.get("tone", "professional")
    demo_mode = payload.get("demo_mode", True)
    upload_folder = payload["upload_folder"]
    store_id = payload["store_id"]

    try:
        if demo_mode:
            content = mock_cover_letter(resume_text, jd_text, tone)
        else:
            from openai import OpenAI
            from utils.llm_config import GROQ_BASE_URL

            api_key = os.getenv("GROQ_API_KEY") or os.getenv("GROQ_KEY")
            client = OpenAI(api_key=api_key, base_url=GROQ_BASE_URL) if api_key else None
            content = generate_cover_letter(client, resume_text, jd_text, tone)
    except Exception as exc:
        logger.exception("cover_letter job failed")
        raise RuntimeError(format_openai_error(exc)) from exc

    save_json(upload_folder, "documents_cover_letter", content, store_id=store_id)
    return {"content": content, "tone": tone}


def run_email(payload: dict) -> dict:
    from utils.email_generator import generate_email, mock_email
    from utils.openai_errors import format_openai_error
    from utils.session_store import save_json

    resume_text = payload["resume_text"]
    jd_text = payload["jd_text"]
    email_type = payload.get("email_type", "job_application")
    demo_mode = payload.get("demo_mode", True)
    upload_folder = payload["upload_folder"]
    store_id = payload["store_id"]

    try:
        if demo_mode:
            result = mock_email(resume_text, jd_text, email_type)
        else:
            from openai import OpenAI
            from utils.llm_config import GROQ_BASE_URL

            api_key = os.getenv("GROQ_API_KEY") or os.getenv("GROQ_KEY")
            client = OpenAI(api_key=api_key, base_url=GROQ_BASE_URL) if api_key else None
            result = generate_email(client, resume_text, jd_text, email_type)
    except Exception as exc:
        logger.exception("email job failed")
        raise RuntimeError(format_openai_error(exc)) from exc

    save_json(upload_folder, "documents_email", result, store_id=store_id)
    return result


TASKS = {
    "career_coach": run_career_coach,
    "cover_letter": run_cover_letter,
    "email": run_email,
}


def execute_task(job_type: str, payload: dict) -> Any:
    fn = TASKS.get(job_type)
    if not fn:
        raise ValueError(f"Unknown job type: {job_type}")
    return fn(payload)
