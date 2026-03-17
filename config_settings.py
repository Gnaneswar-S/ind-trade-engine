"""
config/settings.py   (place at project root as config_settings.py until restructure)
══════════════════════════════════════════════════════════════════
Single source of truth for all app constants.
Import from here — never hardcode values in app.py or services.
══════════════════════════════════════════════════════════════════
"""
import os
import streamlit as st
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── App metadata ──────────────────────────────────────────────────
APP_TITLE    = "🇮🇳 Indian Trade Intelligence Engine"
APP_VERSION  = "3.0.0"
APP_ICON     = "📦"

# ── File paths ────────────────────────────────────────────────────
ROOT_DIR     = Path(__file__).parent
DATA_DIR     = ROOT_DIR / "data"
DATASET_PATH = str(DATA_DIR / "trade_map_2024.xls")

# ── Role-based daily limits ───────────────────────────────────────
# Keep in sync with sql_schema_v3.sql get_daily_limit_for_role()
ROLE_DAILY_LIMITS: dict[str, int] = {
    "free":    10,
    "user":    50,
    "analyst": 150,
    "pro":     500,
    "admin":   999999,
}

ROLE_LABELS: dict[str, str] = {
    "free":    "Free",
    "user":    "Standard",
    "analyst": "Analyst",
    "pro":     "Pro",
    "admin":   "Admin",
}

def get_daily_limit(role: str) -> int:
    return ROLE_DAILY_LIMITS.get(role, ROLE_DAILY_LIMITS["free"])

def get_role_label(role: str) -> str:
    return ROLE_LABELS.get(role, role.upper())

# ── Navigation ────────────────────────────────────────────────────
NAV_SECTIONS: dict[str, list[tuple[str, str]]] = {
    "📊 ANALYTICS": [
        ("dashboard",      "📈 Dashboard"),
        ("trade_analysis", "🔍 Trade Analysis"),
        ("hs_engine",      "🔢 HS Code Engine"),
        ("market_recs",    "🌍 Market Recommendations"),
        ("country_lookup", "🔎 Country Lookup"),
        ("future_trends",  "🔮 Future Trends"),
    ],
    "🤖 AI INTELLIGENCE": [
        ("tradegpt",    "🤖 TradeGPT Chat"),
        ("risk",        "⚠️ Risk Analyzer"),
        ("price_intel", "💰 Price Intelligence"),
        ("competitor",  "🥊 Competitor Intel"),
        ("trade_ideas", "💡 Smart Trade Ideas"),
        ("ai_reports",  "📊 AI Reports"),
    ],
    "🔗 OPERATIONS": [
        ("suppliers",    "🔗 Supplier Finder"),
        ("shipment",     "🚢 Shipment Calculator"),
        ("doc_analyzer", "📄 Document Analyzer"),
        ("compliance",   "📋 Compliance Checker"),
    ],
    "⚙️ ACCOUNT": [
        ("support", "🎫 Support"),
        ("profile", "👤 Profile"),
    ],
}

ADMIN_NAV: list[tuple[str, str]] = [
    ("data_sync", "💾 Data Sync"),
    ("admin",     "🛡️ Admin Panel"),
]

# ── AI model settings ─────────────────────────────────────────────
NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
NVIDIA_MODEL   = "meta/llama-3.3-70b-instruct"
LLM_CACHE_SIZE = 200
LLM_CACHE_TTL  = 3600

# ── Session state defaults ────────────────────────────────────────
SESSION_DEFAULTS: dict = {
    "user":             None,
    "active_page":      "dashboard",
    "rate_info":        None,
    "trade_data":       None,
    # 2FA / password reset
    "otp_pending":      False,
    "otp_email":        None,
    "otp_user_tmp":     None,
    "pw_reset_step":    0,
    "pw_reset_email":   None,
    "pw_reset_done":    False,
    # Cached AI results (cleared on logout)
    "last_result":      None,
    "last_product":     None,
    "last_mode":        None,
    "chat_history":     [],
    "chat_context":     None,
    "risk_result":      None,
    "price_result":     None,
    "comp_result":      None,
    "ideas_result":     None,
    "supplier_result":  None,
    "doc_result":       None,
    "compliance_result":None,
    "report_result":    None,
}

def init_session_state() -> None:
    """Call once at top of app.py to initialise all session keys."""
    for key, default in SESSION_DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = default

# ── Required env vars ─────────────────────────────────────────────
REQUIRED_ENV_VARS = [
    "NVIDIA_API_KEY",
    "SUPABASE_URL",
    "SUPABASE_SERVICE_KEY",
    "SUPABASE_ANON_KEY",
]

def validate_env() -> list[str]:
    """Returns list of missing required env vars. Empty = all good."""
    return [v for v in REQUIRED_ENV_VARS if not os.getenv(v, "").strip()]