import os

# Groq OpenAI-compatible endpoint
GROQ_BASE_URL = "https://api.groq.com/openai/v1"


def get_model():
    """Resolve model at call time so .env is loaded first."""
    return os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
