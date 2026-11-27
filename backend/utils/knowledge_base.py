import os

from utils.pdf_utils import extract_text_from_pdf
from utils.feature_flags import persist_embeddings
from utils.rag import UserKnowledgeBase
from utils.session_store import load_text


def _mock_github_profile(username):
    return f"""GitHub Profile: @{username}
Top Repositories:
- resume-optimizer (Python, Flask) — AI-powered resume tailoring tool
- fullstack-ecommerce (React, Node.js, MongoDB) — MERN stack shopping app
- algo-practice (Python) — Data structures and algorithms solutions

Stats: 24 public repos · 156 commits this year · Primary languages: Python, JavaScript, TypeScript
Notable: Active open-source contributor, strong backend focus"""


def _mock_leetcode_profile(username):
    return f"""LeetCode Profile: @{username}
Problems Solved: 287 total (Easy: 98, Medium: 152, Hard: 37)
Contest Rating: 1,642
Strong topics: Arrays, Hash Maps, Binary Search, Dynamic Programming (basic)
Weak topics: Graph algorithms, Advanced DP, System design
Recent activity: 12 problems solved in the last 30 days"""


def _safe_load_text(upload_folder, name, default="", store_id=None):
    """load_text that never raises outside a Flask request (workers pass store_id)."""
    try:
        return load_text(upload_folder, name, default, store_id=store_id)
    except RuntimeError:
        return default


def _add_doc(kb, source, text, label, user_id=None):
    """Add a document, using DB-cached embeddings when persistence is enabled."""
    if not text or not str(text).strip():
        return
    if user_id and persist_embeddings():
        from utils import db_embeddings
        from utils.embeddings import get_embedder

        kb._embedder = kb._embedder or get_embedder()
        chunks = db_embeddings.load_or_index(user_id, source, text, label, kb._embedder)
        if chunks:
            kb.add_embedded_document(source, text, label, chunks)
            return
    kb.add_document(source, text, label)


def build_knowledge_base(session, upload_folder, user_id=None, store_id=None):
    kb = UserKnowledgeBase()

    filename = session.get("resume_filename")
    if filename:
        paths = []
        if user_id:
            paths.append(os.path.join(upload_folder, "users", user_id, filename))
        paths.append(os.path.join(upload_folder, filename))
        for path in paths:
            if os.path.exists(path):
                resume_text = extract_text_from_pdf(path)
                _add_doc(kb, "resume", resume_text, "Uploaded Resume", user_id)
                break

    jd = _safe_load_text(upload_folder, "jd", "", store_id) or session.get("jd")
    if jd:
        _add_doc(kb, "job_description", jd, "Job Description", user_id)

    optimized = (
        _safe_load_text(upload_folder, "optimized_resume", "", store_id)
        or session.get("optimized_resume")
    )
    if optimized:
        _add_doc(kb, "optimized_resume", optimized, "Previous Optimization", user_id)

    github_user = session.get("github_username")
    if github_user:
        kb.add_document("github", _mock_github_profile(github_user), f"GitHub (@{github_user})")

    leetcode_user = session.get("leetcode_username")
    if leetcode_user:
        kb.add_document("leetcode", _mock_leetcode_profile(leetcode_user), f"LeetCode (@{leetcode_user})")

    return kb
