from openai import APIConnectionError, APIStatusError, AuthenticationError, RateLimitError


def format_openai_error(exc):
    """Format Groq/OpenAI-compatible API errors for the UI."""
    if isinstance(exc, AuthenticationError):
        return (
            "Invalid Groq API key. Check GROQ_API_KEY (or GROQ_KEY) in your .env file."
        )

    if isinstance(exc, RateLimitError):
        body = getattr(exc, "body", None) or {}
        error_info = body.get("error", {}) if isinstance(body, dict) else {}
        if error_info.get("code") in ("insufficient_quota", "rate_limit_exceeded"):
            return (
                "Groq rate limit or quota reached. Wait a moment, or check your "
                "limits at https://console.groq.com/settings/limits then try again."
            )
        return "Groq rate limit reached. Please wait a moment and try again."

    if isinstance(exc, APIConnectionError):
        return "Could not connect to Groq. Check your internet connection and try again."

    if isinstance(exc, APIStatusError):
        return f"Groq API error ({exc.status_code}). Please try again later."

    return "An unexpected Groq API error occurred. Please try again later."
