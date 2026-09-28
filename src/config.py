"""
Central configuration for the triage pipeline.

All tunables live here so Task 3 (evals) and Task 2 (account summariser)
can import the same settings instead of hardcoding them per-module.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# --- Paths -------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
KB_DIR = ROOT_DIR / "knowledge-base"

TICKETS_PATH = DATA_DIR / "tickets.json"
ACCOUNTS_PATH = DATA_DIR / "accounts.json"

# --- LLM settings --------------------------------------------------------
# Groq exposes an OpenAI-compatible API, so we reuse the `openai` SDK and
# just point it at Groq's base URL instead of OpenAI's.
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_BASE_URL = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
MODEL_NAME = os.environ.get("TRIAGE_MODEL", "openai/gpt-oss-120b")
MODEL_TEMPERATURE = float(os.environ.get("TRIAGE_TEMPERATURE", "0"))
MODEL_MAX_TOKENS = int(os.environ.get("TRIAGE_MAX_TOKENS", "1024"))

# --- Retrieval settings --------------------------------------------------
# Local sentence-transformers model - small, fast, no external API calls
# (downloaded once from huggingface.co and cached locally thereafter).
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
KB_TOP_K = int(os.environ.get("KB_TOP_K", "3"))
# Cosine similarity threshold below which we treat retrieval as "no
# confident match" rather than surfacing a weak/irrelevant doc.
KB_MIN_SCORE = float(os.environ.get("KB_MIN_SCORE", "0.35"))

# --- Routing table ---------------------------------------------------
# Maps product_area / category -> responder team.
# Used as a deterministic fallback / cross-check alongside the LLM's own
# recommendation, so a bad LLM guess can't silently misroute a P1.
CATEGORY_TEAM_MAP = {
    "Bug": "Technical Support - Tier 2",
    "Performance": "Technical Support - Tier 2",
    "Data Loss": "Technical Support - Tier 2 (Escalations)",
    "Integration": "Technical Support - Integrations",
    "Billing": "Billing & Accounts",
    "Feature Request": "Product Team",
    "How-To": "Technical Support - Tier 1",
    "Onboarding": "Customer Onboarding",
}

DEFAULT_TEAM = "Technical Support - Tier 1"
