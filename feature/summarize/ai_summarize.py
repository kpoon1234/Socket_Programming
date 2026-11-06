"""Call the AI provider without exposing credentials or provider response bodies."""

import os
from pathlib import Path

try:
    from dotenv import dotenv_values
except ImportError:
    dotenv_values = None

try:
    from groq import (
        APIConnectionError,
        APIError,
        APIStatusError,
        APITimeoutError,
        AuthenticationError,
        Groq,
        PermissionDeniedError,
        RateLimitError,
    )
except ImportError:
    APIConnectionError = APIError = APIStatusError = APITimeoutError = ()
    AuthenticationError = PermissionDeniedError = RateLimitError = ()
    Groq = None

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
DEFAULT_MODEL = "openai/gpt-oss-20b"


class SummaryError(Exception):
    """An error code and safe message suitable for returning to the requester."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def summarize_text(system_prompt, conversation):
    """Return a completed summary. Call from a worker, outside chat state locks."""
    if not isinstance(conversation, str) or not conversation.strip():
        raise SummaryError("no_messages", "There are no messages to summarize.")
    if not isinstance(system_prompt, str) or not system_prompt.strip():
        raise SummaryError("invalid_prompt", "A summary instruction is required.")
    if dotenv_values is None or Groq is None:
        raise SummaryError("configuration_error", "AI summarization libraries are not installed.")

    # อ่านเฉพาะ .env ของโปรเจกต์ ไม่เปลี่ยน environment ของโปรแกรม
    # environment ที่ตั้งไว้มีสิทธิ์เหนือไฟล์ และไม่ขยายตัวแปรในค่าลับ
    try:
        settings = dotenv_values(ENV_PATH, interpolate=False)
    except (OSError, UnicodeError):
        raise SummaryError("configuration_error", "Could not read the server AI configuration.") from None
    api_key = (os.environ.get("GROQ_API_KEY", settings.get("GROQ_API_KEY")) or "").strip()
    model = (os.environ.get("GROQ_MODEL", settings.get("GROQ_MODEL")) or "").strip()
    if not api_key or api_key == "your_groq_api_key_here":
        raise SummaryError("missing_api_key", "AI summarization is not configured on the server.")
    if not model or model == "your_model_id_here":
        model = DEFAULT_MODEL

    try:
        # จำกัดเวลารอ ปิด retry และไม่เปิด tools ให้โมเดล
        with Groq(api_key=api_key, timeout=30.0, max_retries=0) as client:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": conversation},
                ],
                temperature=0.2,
                max_completion_tokens=2048,
            )
    except AuthenticationError:
        error = SummaryError("authentication_error", "The AI provider rejected the server API key.")
    except PermissionDeniedError:
        error = SummaryError("permission_denied", "The server cannot access this AI model.")
    except RateLimitError:
        error = SummaryError("rate_limited", "The AI quota is full. Please try again later.")
    except APITimeoutError:
        error = SummaryError("timeout", "The AI provider timed out. Please try again later.")
    except APIConnectionError:
        error = SummaryError("connection_error", "Could not connect to the AI provider.")
    except APIStatusError:
        error = SummaryError("provider_error", "The AI request failed. Check the server model and provider status.")
    except APIError:
        error = SummaryError("provider_error", "The AI provider returned an invalid response.")
    else:
        if not response.choices:
            raise SummaryError("empty_summary", "The AI provider returned no summary.")
        choice = response.choices[0]
        if choice.finish_reason != "stop":
            raise SummaryError("incomplete_summary", "The AI summary was not completed. Please try again.")
        text = choice.message.content
        if not isinstance(text, str) or not text.strip():
            raise SummaryError("empty_summary", "The AI provider returned no summary.")
        return text.strip()

    # ไม่แนบ exception เดิม ซึ่งอาจมี key, prompt หรือ response body
    raise error from None
