"""
app.py
🇮🇳 Indian Trade Intelligence Engine — Production SaaS Dashboard v3.0
──────────────────────────────────────────────────────────────────────
Architecture: Sidebar navigation, lazy-loaded modules, st.cache_data/resource,
              professional SaaS UI, enhanced security, OCR document scanning,
              atomic server-side rate limiting (query_limiter.py).

Rate limit fix summary:
  ✅ consume_query() RPC called after every AI response (atomic, no bypass)
  ✅ rate_guard()    uses fresh 30s-cached status — NOT stale session_state
  ✅ Sidebar bar     reads same cache (render_rate_bar from query_limiter)
  ✅ No Python-side counter — single source of truth is the DB
──────────────────────────────────────────────────────────────────────
"""

import os
import json as _json
import logging
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime

# ── Structured logging ───────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("trade_engine")

# ── Rate limiter (MUST import before service imports) ────────────────
from query_limiter import rate_guard, consume_query, render_rate_bar, get_limit_status

# ── Service imports ──────────────────────────────────────────────────
from nvidia_service import trade_intelligence_engine
from trade_advisor import (
    chat_with_tradegpt, analyze_trade_risk, get_price_intelligence,
    analyze_trade_document, check_trade_compliance, get_competitor_intelligence,
    generate_smart_trade_ideas, find_global_suppliers, generate_ai_trade_report,
)
from hs_engine import classify_and_enrich, calculate_shipment_cost, get_dataset_status
from supabase_service import (
    sign_up_user, login_user, login_with_token, logout_user,
    log_trade_usage, get_user_stats,
    notify_all_users_new_dataset, notify_user_limit_warning,
    request_password_reset, verify_reset_otp, admin_update_user_password,
    smtp_diagnostic, exchange_code_for_session, update_user_password,
    get_platform_stats, get_all_users, get_all_queries, update_user_role,
)
from email_confirmation import (
    handle_confirmation_callback,
    render_confirmation_pending,
    render_confirmed_success,
)
from trade_data_service import (
    load_trade_data, get_top_markets, get_future_trends,
    get_country_stats, get_dashboard_data,
    upload_trade_data_to_supabase, log_market_lookup,
)
from otp_service import send_otp_email, verify_otp
from report_service import export_to_excel, export_to_pdf, get_report_filename
from admin_dashboard import render_admin_dashboard
from support_service import (
    submit_ticket, get_user_tickets,
    TICKET_TYPES, STATUS_LABELS, PRIORITY_LABELS,
)
from document_scanner import scan_document, SUPPORTED_FORMATS

# ════════════════════════════════════════════════════════════════════
# PAGE CONFIG
# ════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="Trade Intelligence Engine",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global CSS ───────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

html, body, [class*="css"], .stApp {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
}

/* Sidebar styling */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0a0f1e 0%, #0d1627 50%, #0a0f1e 100%);
    border-right: 1px solid #1e2d45;
}
[data-testid="stSidebar"] .stMarkdown { color: #a0aec0; }
[data-testid="stSidebar"] button {
    background: transparent !important;
    border: none !important;
    text-align: left !important;
    padding: 10px 16px !important;
    border-radius: 8px !important;
    color: #8b9ab3 !important;
    font-size: 0.875rem !important;
    font-weight: 500 !important;
    width: 100% !important;
    transition: all 0.15s ease !important;
}
[data-testid="stSidebar"] button:hover {
    background: rgba(26,111,168,0.15) !important;
    color: #63b3ed !important;
    transform: none !important;
    box-shadow: none !important;
}

/* Main content */
.main .block-container { padding: 1.5rem 2rem; max-width: 1400px; }

/* Metric cards */
[data-testid="metric-container"] {
    background: linear-gradient(135deg, #0d1627 0%, #111827 100%);
    border: 1px solid #1e2d45;
    border-radius: 14px;
    padding: 18px 20px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.3);
    transition: transform 0.2s ease, box-shadow 0.2s ease;
}
[data-testid="metric-container"]:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 30px rgba(0,0,0,0.4);
}
[data-testid="metric-container"] label { color: #6b7a99 !important; font-size: 0.75rem !important; font-weight: 500 !important; letter-spacing: 0.05em; text-transform: uppercase; }
[data-testid="metric-container"] [data-testid="metric-value"] { color: #e2e8f0 !important; font-size: 1.6rem !important; font-weight: 700 !important; }
[data-testid="metric-container"] [data-testid="metric-delta"] { font-size: 0.78rem !important; }

/* Tab styling */
.stTabs [data-baseweb="tab-list"] { gap: 4px; flex-wrap: wrap; background: transparent; border-bottom: 1px solid #1e2d45; padding-bottom: 0; }
.stTabs [data-baseweb="tab"] { border-radius: 8px 8px 0 0; padding: 8px 16px; font-size: 0.82rem; font-weight: 500; color: #8b9ab3; background: transparent; border: none; }
.stTabs [aria-selected="true"] { background: linear-gradient(135deg,#1a3a6e,#0f3460) !important; color: white !important; }

/* Buttons */
.stButton > button {
    border-radius: 10px;
    font-weight: 600;
    font-size: 0.875rem;
    transition: all 0.2s ease;
    border: 1px solid transparent;
}
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #1a6fa8, #0f3460);
    border-color: #1a6fa8;
    color: white;
}
.stButton > button[kind="primary"]:hover {
    background: linear-gradient(135deg, #2280c0, #1a4a80);
    transform: translateY(-1px);
    box-shadow: 0 6px 20px rgba(26,111,168,0.4);
}

/* Cards */
.saas-card {
    background: linear-gradient(135deg, #0d1627 0%, #111827 100%);
    border: 1px solid #1e2d45;
    border-radius: 16px;
    padding: 24px;
    margin: 8px 0;
    box-shadow: 0 4px 20px rgba(0,0,0,0.2);
}
.info-card {
    background: #0d1627;
    border: 1px solid #1e2d45;
    border-radius: 12px;
    padding: 16px;
    margin: 6px 0;
}
.highlight-card {
    background: linear-gradient(135deg, #0d2040, #0a1a35);
    border: 1px solid #1a6fa8;
    border-radius: 12px;
    padding: 16px;
}

/* Status badges */
.badge-success { background: rgba(72,187,120,0.15); color: #48bb78; padding: 3px 10px; border-radius: 20px; font-size: 0.75rem; font-weight: 600; border: 1px solid rgba(72,187,120,0.3); }
.badge-warning { background: rgba(236,201,75,0.15); color: #ecc94b; padding: 3px 10px; border-radius: 20px; font-size: 0.75rem; font-weight: 600; border: 1px solid rgba(236,201,75,0.3); }
.badge-danger  { background: rgba(252,129,129,0.15); color: #fc8181; padding: 3px 10px; border-radius: 20px; font-size: 0.75rem; font-weight: 600; border: 1px solid rgba(252,129,129,0.3); }
.badge-info    { background: rgba(99,179,237,0.15); color: #63b3ed; padding: 3px 10px; border-radius: 20px; font-size: 0.75rem; font-weight: 600; border: 1px solid rgba(99,179,237,0.3); }

/* Admin badge */
.admin-badge { background: linear-gradient(135deg,#f6d365,#fda085); color:#1a1a2e; font-size:0.65rem; font-weight:700; padding:2px 8px; border-radius:20px; margin-left:6px; vertical-align:middle; }

/* Confidence indicators */
.conf-high { color:#48bb78; font-weight:600; }
.conf-med  { color:#ecc94b; font-weight:600; }
.conf-low  { color:#fc8181; font-weight:600; }

/* Auth page */
.auth-container { max-width: 480px; margin: 0 auto; padding: 2rem 0; }
.auth-card { background: #0d1627; border: 1px solid #1e2d45; border-radius: 18px; padding: 36px 40px; box-shadow: 0 20px 60px rgba(0,0,0,0.4); }

/* Rate bar */
.rate-bar-wrap { background: #0d1627; border-radius: 10px; padding: 10px 14px; margin-bottom: 4px; border: 1px solid #1e2d45; }

/* Dividers */
.section-divider { height: 1px; background: linear-gradient(90deg, transparent, #1e2d45, transparent); margin: 16px 0; }

/* Sidebar nav sections */
.nav-section-header { color: #4a5568 !important; font-size: 0.65rem !important; font-weight: 700 !important; letter-spacing: 0.12em !important; text-transform: uppercase !important; padding: 12px 16px 4px !important; }

/* Input fields */
.stTextInput input, .stTextArea textarea, .stSelectbox select {
    background: #0d1627 !important;
    border: 1px solid #1e2d45 !important;
    border-radius: 10px !important;
    color: #e2e8f0 !important;
    font-size: 0.875rem !important;
}
.stTextInput input:focus, .stTextArea textarea:focus {
    border-color: #1a6fa8 !important;
    box-shadow: 0 0 0 3px rgba(26,111,168,0.15) !important;
}

/* Page header */
.page-header {
    background: linear-gradient(135deg, #0d1627, #111827);
    border: 1px solid #1e2d45;
    border-radius: 16px;
    padding: 20px 28px;
    margin-bottom: 24px;
}

/* Scrollbar */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #0a0f1e; }
::-webkit-scrollbar-thumb { background: #1e2d45; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #2d4a70; }

/* Mobile */
@media (max-width: 768px) {
    .main .block-container { padding: 0.75rem; }
    .auth-card { padding: 20px; }
}
</style>
""", unsafe_allow_html=True)

DATASET_PATH = os.path.join(os.path.dirname(__file__), "data", "trade_map_2024.xls")

# ════════════════════════════════════════════════════════════════════
# SESSION STATE DEFAULTS
# ════════════════════════════════════════════════════════════════════
_DEFAULTS = {
    "user": None,
    "trade_data": None,
    "db_uploaded": False,
    "rate_info": None,
    "active_page": "dashboard",
    # 2FA
    "otp_pending": False, "otp_email": None, "otp_user_tmp": None,
    # Password reset
    "pw_reset_step": 0, "pw_reset_email": None, "pw_reset_done": False,
    # Results cache
    "last_result": None, "last_product": None, "last_mode": None,
    "chat_history": [], "chat_context": None,
    "risk_result": None, "price_result": None, "comp_result": None,
    "ideas_result": None, "supplier_result": None, "doc_result": None,
    "compliance_result": None, "report_result": None,
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ════════════════════════════════════════════════════════════════════
# CACHED DATA LOADERS
# ════════════════════════════════════════════════════════════════════
@st.cache_data(show_spinner=False)
def _load_trade_data_cached(path: str):
    logger.info(f"Loading trade dataset from {path}")
    return load_trade_data(path)

@st.cache_resource(show_spinner=False)
def _get_plotly_config():
    return {"displayModeBar": False, "responsive": True}

def get_trade_data() -> list:
    if st.session_state.trade_data is None and os.path.exists(DATASET_PATH):
        st.session_state.trade_data = _load_trade_data_cached(DATASET_PATH)
    return st.session_state.trade_data or []

# NOTE: _cached_rate_limit removed in v3.
# Use rate_guard(user) for page gates, consume_query(user_id) after AI calls.
# get_limit_status(user_id) for display (30s cache, from query_limiter).

# ════════════════════════════════════════════════════════════════════
# URL TOKEN HANDLER (email confirmation)
# ════════════════════════════════════════════════════════════════════
def _handle_url_tokens() -> None:
    """
    Detect Supabase email-confirmation callbacks (?code= or ?access_token=).
    Delegates to email_confirmation module which handles both PKCE and implicit
    flows, auto-logs the user in, and shows the beautiful success/error screen.
    """
    if handle_confirmation_callback():
        # handle_confirmation_callback() already rendered the success/error screen.
        # st.stop() prevents the rest of app.py from rendering on top of it.
        st.stop()

_handle_url_tokens()

# ════════════════════════════════════════════════════════════════════
# SIDEBAR NAVIGATION
# ════════════════════════════════════════════════════════════════════
NAV_SECTIONS = {
    "📊 Analytics": [
        ("dashboard",       "📈 Dashboard"),
        ("trade_analysis",  "🔍 Trade Analysis"),
        ("hs_engine",       "🔢 HS Code Engine"),
        ("market_recs",     "🌍 Market Recommendations"),
        ("country_lookup",  "🔎 Country Lookup"),
        ("future_trends",   "🔮 Future Trends"),
    ],
    "🤖 AI Intelligence": [
        ("tradegpt",        "🤖 TradeGPT Chat"),
        ("risk",            "⚠️ Risk Analyzer"),
        ("price_intel",     "💰 Price Intelligence"),
        ("competitor",      "🥊 Competitor Intel"),
        ("trade_ideas",     "💡 Smart Trade Ideas"),
        ("ai_reports",      "📊 AI Reports"),
    ],
    "🔗 Operations": [
        ("suppliers",       "🔗 Supplier Finder"),
        ("shipment",        "🚢 Shipment Calculator"),
        ("doc_analyzer",    "📄 Document Analyzer"),
        ("compliance",      "📋 Compliance Checker"),
    ],
    "⚙️ Account": [
        ("support",         "🎫 Support"),
        ("profile",         "👤 Profile"),
    ],
}

ADMIN_NAV = [
    ("data_sync",      "💾 Data Sync"),
    ("admin",          "🛡️ Admin Panel"),
]

def render_sidebar(user: dict) -> str:
    """Render sidebar, return currently selected page key."""
    is_admin = user.get("is_admin", False)
    role     = user.get("role", "free")
    email    = user.get("email", "")

    with st.sidebar:
        # ── Logo / Brand ─────────────────────────────────────
        st.markdown("""
        <div style="padding: 20px 16px 12px; text-align: center;">
          <div style="font-size: 2rem;">🇮🇳</div>
          <div style="color: #e2e8f0; font-size: 1rem; font-weight: 700; margin: 4px 0 2px;">
            Trade Intelligence
          </div>
          <div style="color: #4a5568; font-size: 0.72rem;">Powered by Llama 3.3 70B</div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)

        # ── User info strip ───────────────────────────────────
        plan_badge = {
            "free": "🆓 Free", "user": "👤 User",
            "pro": "⭐ Pro", "admin": "🛡️ Admin"
        }.get(role, role.upper())
        admin_tag = ' <span class="admin-badge">ADMIN</span>' if is_admin else ""
        st.markdown(f"""
        <div style="padding: 10px 16px; background: rgba(26,111,168,0.08);
                    border-radius: 10px; margin: 0 8px 12px;">
          <div style="color: #e2e8f0; font-size: 0.82rem; font-weight: 600;">
            {email.split('@')[0]}{admin_tag}
          </div>
          <div style="color: #4a5568; font-size: 0.72rem;">{plan_badge} · {email}</div>
        </div>
        """, unsafe_allow_html=True)

        # ── Rate limit mini-bar ───────────────────────────────
        try:
            ri = render_rate_bar(user["id"], role)
            # Only update rate_info if sidebar read is >= freshly-consumed count.
            # This prevents the sidebar overwriting a count just set by _consume_and_refresh.
            if not st.session_state.get("rate_info") or \
               st.session_state.rate_info.get("queries_today", 0) <= ri.get("queries_today", 0):
                st.session_state.rate_info = ri
        except Exception:
            pass

        st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)

        # ── Navigation ────────────────────────────────────────
        active_page = st.session_state.active_page

        for section_label, items in NAV_SECTIONS.items():
            st.markdown(f'<div class="nav-section-header">{section_label}</div>', unsafe_allow_html=True)
            for page_key, page_label in items:
                is_active = active_page == page_key
                btn_style = "background: rgba(26,111,168,0.2) !important; color: #63b3ed !important; border-left: 3px solid #1a6fa8 !important;" if is_active else ""
                if st.button(
                    page_label,
                    key=f"nav_{page_key}",
                    use_container_width=True,
                ):
                    st.session_state.active_page = page_key
                    active_page = page_key
                    st.rerun()

        if is_admin:
            st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
            st.markdown('<div class="nav-section-header">🛡️ Administration</div>', unsafe_allow_html=True)
            for page_key, page_label in ADMIN_NAV:
                if st.button(page_label, key=f"nav_{page_key}", use_container_width=True):
                    st.session_state.active_page = page_key
                    st.rerun()

        st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)

        # ── Logout ────────────────────────────────────────────
        if st.button("🚪 Logout", use_container_width=True, key="sidebar_logout"):
            logout_user(user["id"], user["email"])
            # Clear ALL session state including cached rate info
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()

        st.markdown("""
        <div style="padding: 12px 16px; text-align: center;">
          <span style="color: #1e2d45; font-size: 0.65rem;">v2.0 · ITC Trade Map 2024</span>
        </div>
        """, unsafe_allow_html=True)

    return st.session_state.active_page

# ════════════════════════════════════════════════════════════════════
# SHARED WIDGETS
# ════════════════════════════════════════════════════════════════════
def page_header(title: str, subtitle: str = "", icon: str = "") -> None:
    st.markdown(f"""
    <div class="page-header">
      <div style="display:flex;align-items:center;gap:12px;">
        <span style="font-size:1.8rem;">{icon}</span>
        <div>
          <h2 style="color:#e2e8f0;margin:0;font-size:1.3rem;font-weight:700;">{title}</h2>
          {f'<p style="color:#6b7a99;margin:2px 0 0;font-size:0.82rem;">{subtitle}</p>' if subtitle else ''}
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

def render_rate_limit_bar() -> dict:
    """Delegates to query_limiter.render_rate_bar. Kept for backward compat."""
    user = st.session_state.user
    from query_limiter import render_rate_bar
    info = render_rate_bar(user["id"], user.get("role", "free"))
    st.session_state.rate_info = info
    return info

def _download_row(result: dict, product: str, mode: str, email: str) -> None:
    st.markdown("#### 📥 Download Report")
    dc1, dc2, dc3 = st.columns(3)
    with dc1:
        try:
            buf  = export_to_excel(result, product, mode, email)
            st.download_button("📊 Excel (.xlsx)", data=buf,
                file_name=get_report_filename(product, mode, "xlsx"),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True)
        except Exception as e:
            st.error(f"Excel: {e}")
    with dc2:
        try:
            buf  = export_to_pdf(result, product, mode, email)
            st.download_button("📄 PDF (.pdf)", data=buf,
                file_name=get_report_filename(product, mode, "pdf"),
                mime="application/pdf", use_container_width=True)
        except Exception as e:
            st.error(f"PDF: {e}")
    with dc3:
        st.download_button("📋 JSON (.json)",
            data=_json.dumps(result, indent=2),
            file_name=get_report_filename(product, mode, "json"),
            mime="application/json", use_container_width=True)

def _rate_guard() -> bool:
    """
    Pre-flight gate for AI pages. Delegates to query_limiter.rate_guard().

    v3 fix: No longer reads st.session_state.rate_info for enforcement.
    Uses 30s-cached get_limit_status() for display pre-check.
    Actual decrement happens via consume_query() AFTER AI call.
    """
    return rate_guard(st.session_state.user)
def _page_password_reset() -> None:
    step  = st.session_state.get("pw_reset_step", 0)
    email = st.session_state.get("pw_reset_email", "")
    if step == 0:
        return

    _, center, _ = st.columns([1, 2, 1])
    with center:
        if step == 1:
            st.markdown(f"""
            <div class="auth-card" style="text-align:center;margin-top:24px;">
              <div style="font-size:3rem;">📧</div>
              <h2 style="color:#e2e8f0;font-size:1.4rem;margin:10px 0 6px;">Check Your Email</h2>
              <p style="color:#8b949e;font-size:0.88rem;margin:0;">
                We sent a 6-digit reset code to<br>
                <strong style="color:#63b3ed;">{email}</strong>
              </p>
              <p style="color:#4a5568;font-size:0.78rem;margin:8px 0 0;">⏱ Expires in 5 minutes</p>
            </div>
            """, unsafe_allow_html=True)
            st.markdown("<br>", unsafe_allow_html=True)
            with st.form("pr_otp_form"):
                otp_val = st.text_input("🔢 Enter 6-digit Reset Code", placeholder="e.g. 482931", max_chars=6)
                c1, c2 = st.columns(2)
                with c1: verify_btn = st.form_submit_button("✅ Verify Code", use_container_width=True, type="primary")
                with c2: resend_btn = st.form_submit_button("🔄 Resend Code", use_container_width=True)
            if verify_btn:
                if not otp_val.strip():
                    st.error("Please enter the code.")
                else:
                    with st.spinner("Verifying..."):
                        res = verify_reset_otp(email, otp_val.strip())
                    if res["status"] == "success":
                        st.session_state.pw_reset_step = 2
                        st.rerun()
                    else:
                        st.error(f"❌ {res['message']}")
            if resend_btn:
                with st.spinner("Sending..."):
                    res = request_password_reset(email)
                st.success("✅ New code sent.")
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("← Back to Login", use_container_width=True):
                st.session_state.pw_reset_step = 0
                st.session_state.pw_reset_email = None
                st.rerun()

        elif step == 2:
            st.markdown("""
            <div class="auth-card" style="text-align:center;margin-top:24px;">
              <div style="font-size:3rem;">🔑</div>
              <h2 style="color:#e2e8f0;font-size:1.4rem;margin:10px 0 6px;">Set New Password</h2>
              <p style="color:#8b949e;font-size:0.88rem;margin:0;">Code verified ✅ · Choose a new password</p>
            </div>
            """, unsafe_allow_html=True)
            st.markdown("<br>", unsafe_allow_html=True)
            with st.form("pr_pw_form"):
                pw1 = st.text_input("🔑 New Password", type="password", placeholder="Min 6 characters")
                pw2 = st.text_input("🔑 Confirm Password", type="password", placeholder="Repeat new password")
                save_btn = st.form_submit_button("✅ Update Password", use_container_width=True, type="primary")
            if save_btn:
                if not pw1 or not pw2: st.error("Please fill in both fields.")
                elif pw1 != pw2: st.error("❌ Passwords do not match.")
                elif len(pw1) < 6: st.error("❌ Password must be at least 6 characters.")
                else:
                    with st.spinner("Updating..."):
                        res = admin_update_user_password(email, pw1)
                    if res["status"] == "success":
                        st.session_state.pw_reset_step  = 0
                        st.session_state.pw_reset_email = None
                        st.session_state.pw_reset_done  = True
                        st.balloons()
                        st.rerun()
                    else:
                        st.error(f"❌ {res['message']}")
            if st.button("← Back to Login", use_container_width=True):
                st.session_state.pw_reset_step = 0
                st.session_state.pw_reset_email = None
                st.rerun()

def _page_otp_verification() -> None:
    _, center, _ = st.columns([1, 2, 1])
    email = st.session_state.otp_email
    with center:
        st.markdown(f"""
        <div class="auth-card" style="text-align:center;">
          <div style="font-size:3rem;">🔐</div>
          <h2 style="color:#e2e8f0;font-size:1.5rem;margin:10px 0 6px;">Two-Factor Verification</h2>
          <p style="color:#8b949e;font-size:0.9rem;margin:0;">
            A 6-digit code was sent to<br>
            <strong style="color:#63b3ed;">{email}</strong>
          </p>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        with st.form("otp_form"):
            otp_val = st.text_input("Enter 6-digit OTP", placeholder="e.g. 482931", max_chars=6)
            c1, c2 = st.columns(2)
            with c1: verify = st.form_submit_button("✅ Verify & Login", use_container_width=True, type="primary")
            with c2: resend = st.form_submit_button("🔄 Resend OTP", use_container_width=True)
        if verify:
            if not otp_val.strip(): st.error("Please enter the OTP.")
            else:
                with st.spinner("Verifying..."):
                    res = verify_otp(email, otp_val.strip())
                if res["status"] == "success":
                    st.session_state.user       = st.session_state.otp_user_tmp
                    st.session_state.otp_pending  = False
                    st.session_state.otp_email    = None
                    st.session_state.otp_user_tmp = None
                    st.balloons()
                    st.rerun()
                else:
                    st.error(f"❌ {res['message']}")
        if resend:
            with st.spinner("Sending..."):
                res = send_otp_email(email, email.split("@")[0])
            if res["status"] == "success": st.success("✅ New OTP sent.")
            else: st.warning(f"⚠️ {res['message']}")
        st.markdown("---")
        if st.button("← Back to Login", use_container_width=True):
            st.session_state.otp_pending  = False
            st.session_state.otp_email    = None
            st.session_state.otp_user_tmp = None
            st.rerun()

def login_page() -> None:
    if st.session_state.get("pw_reset_step", 0) > 0 or st.session_state.get("pw_reset_done"):
        _page_password_reset()
        return
    if st.session_state.otp_pending:
        _page_otp_verification()
        return

    # Centre-column layout
    col_l, center, col_r = st.columns([1, 2, 1])
    with center:
        st.markdown("""
        <div style="text-align:center;padding:2.5rem 0 1.5rem;">
          <div style="font-size:3rem;margin-bottom:8px;">🇮🇳</div>
          <h1 style="font-size:1.9rem;font-weight:800;color:#e2e8f0;margin:0 0 4px;">
            Trade Intelligence Engine
          </h1>
          <p style="color:#4a5568;font-size:0.88rem;margin:0;">
            Llama 3.3 70B &nbsp;·&nbsp; ITC Trade Map 2024 &nbsp;·&nbsp; Production Grade
          </p>
        </div>
        """, unsafe_allow_html=True)

        with st.container():
            tab_login, tab_reg, tab_forgot = st.tabs(["🔐 Sign In", "📝 Register", "🔑 Reset Password"])

            with tab_login:
                st.markdown("<br>", unsafe_allow_html=True)
                with st.form("login_form"):
                    email    = st.text_input("Email address", placeholder="you@example.com")
                    password = st.text_input("Password", type="password", placeholder="••••••••")
                    c1, c2 = st.columns([2, 1])
                    with c1:
                        enable_2fa = st.checkbox("Enable 2FA (email OTP)", value=False)
                    with c2:
                        pass
                    submit = st.form_submit_button("Sign In →", use_container_width=True, type="primary")

                if submit:
                    if not email or not password:
                        st.error("Please fill in both fields.")
                    else:
                        with st.spinner("Authenticating..."):
                            result = login_user(email, password)
                        if result["status"] == "success":
                            if enable_2fa:
                                with st.spinner("Sending OTP..."):
                                    otp_res = send_otp_email(email, email.split("@")[0])
                                if otp_res["status"] == "success":
                                    st.session_state.otp_pending  = True
                                    st.session_state.otp_email    = email
                                    st.session_state.otp_user_tmp = result["user"]
                                    st.rerun()
                                else:
                                    st.session_state.user = result["user"]
                                    # Force-clear rate cache so first render reads DB
                                    st.session_state.pop("_ql_live", None)
                                    st.session_state.rate_info = None
                                    st.rerun()
                            else:
                                st.session_state.user = result["user"]
                                # Force-clear rate cache so first render reads fresh count from DB
                                st.session_state.pop("_ql_live", None)
                                st.session_state.rate_info = None
                                logger.info(f"User logged in: {email}")
                                st.rerun()
                        else:
                            st.error(f"❌ {result['message']}")

            with tab_reg:
                st.markdown("<br>", unsafe_allow_html=True)
                with st.form("register_form"):
                    r_email = st.text_input("Email address", placeholder="you@example.com", key="reg_email")
                    r_pw    = st.text_input("Password", type="password", placeholder="Min 6 characters", key="reg_pw")
                    r_pw2   = st.text_input("Confirm Password", type="password", placeholder="Repeat password", key="reg_pw2")
                    r_sub   = st.form_submit_button("Create Account →", use_container_width=True, type="primary")
                if r_sub:
                    if not r_email or not r_pw or not r_pw2: st.error("Please fill in all fields.")
                    elif r_pw != r_pw2: st.error("❌ Passwords do not match.")
                    elif len(r_pw) < 6: st.error("❌ Password must be at least 6 characters.")
                    else:
                        with st.spinner("Creating account..."):
                            result = sign_up_user(r_email, r_pw)
                        if result["status"] == "success":
                            if result.get("email_confirmation_required"):
                                # Show beautiful confirmation pending screen
                                render_confirmation_pending(r_email)
                                st.stop()   # Don't render login form on top of the card
                            else:
                                st.success("✅ Account created! Please sign in.")
                                st.balloons()
                        else:
                            # Show error with code-specific help text
                            code = result.get("code", "")
                            msg  = result.get("message", "Registration failed.")
                            st.error(f"❌ {msg}")
                            if code == "already_registered":
                                st.info("💡 Already have an account? Switch to the **Sign In** tab above.")
                            elif code == "signups_disabled":
                                st.info("📧 Contact the admin to enable registrations.")
                            elif code == "rate_limited":
                                st.warning("⏳ Please wait a few minutes before trying again.")

            with tab_forgot:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.session_state.get("pw_reset_done"):
                    st.success("✅ Password updated! Sign in with your new password.")
                    if st.button("← Back to Sign In", use_container_width=True, type="primary"):
                        st.session_state.pw_reset_done = False
                        st.rerun()
                else:
                    st.markdown("""
                    <div style="background:#0d1627;border:1px solid #1e2d45;border-radius:10px;padding:12px 16px;margin-bottom:16px;">
                      <p style="color:#8b949e;margin:0;font-size:0.88rem;">
                        Enter your account email to receive a <strong style="color:#e2e8f0;">6-digit reset code</strong>.
                        No redirect links needed.
                      </p>
                    </div>
                    """, unsafe_allow_html=True)
                    with st.expander("⚙️ Test email configuration"):
                        if st.button("🔌 Run SMTP Test", key="smtp_test"):
                            with st.spinner("Testing..."):
                                diag = smtp_diagnostic()
                            if diag["status"] == "success": st.success(f"✅ {diag['message']}")
                            else: st.error(f"❌ {diag['message']}")
                    with st.form("forgot_pw_form"):
                        fp_email = st.text_input("Account email", placeholder="you@example.com")
                        fp_sub   = st.form_submit_button("📨 Send Reset Code", use_container_width=True, type="primary")
                    if fp_sub:
                        if not fp_email.strip():
                            st.error("Please enter your email address.")
                        else:
                            with st.spinner("Sending reset code..."):
                                result = request_password_reset(fp_email.strip())
                            if result["status"] == "error":
                                st.error(f"❌ {result['message']}")
                            else:
                                st.session_state.pw_reset_step  = 1
                                st.session_state.pw_reset_email = fp_email.strip()
                                st.rerun()


def _consume_and_refresh(user_id: str) -> dict:
    """
    Call consume_query and immediately sync result into session_state so
    the rate bar and query counter update on the very next render without
    needing an extra DB round-trip.

    Updates BOTH st.session_state.rate_info (used by page display)
    AND st.session_state._ql_live (used by query_limiter sidebar bar)
    so they never diverge after a query is consumed.
    """
    from query_limiter import _ss_set, ROLE_DAILY_LIMITS
    result = consume_query(user_id)
    if isinstance(result, dict) and "queries_today" in result:
        used  = result.get("queries_today", 0)
        limit = result.get("daily_limit", 10)
        remaining = result.get("remaining", max(0, limit - used))
        reset_at  = result.get("reset_at", "")
        status    = result.get("status", "ok")
        # Sync display dict (used by page headers and dashboard)
        st.session_state.rate_info = {
            "queries_today": used,
            "daily_limit":   limit,
            "remaining":     remaining,
            "used":          used,
            "reset_at":      reset_at,
            "status":        status,
        }
        # Also sync the query_limiter's own session cache so sidebar
        # rate bar reflects the updated count immediately
        try:
            _ss_set(user_id, used, limit)
        except Exception:
            pass
    return result

# ════════════════════════════════════════════════════════════════════
# PAGE: DASHBOARD (landing page after login)
# ════════════════════════════════════════════════════════════════════
def page_dashboard(records: list) -> None:
    user = st.session_state.user
    page_header("Dashboard", "Welcome back! Here's your trade intelligence overview.", "📈")

    # ── Quick stats ──────────────────────────────────────────────
    stats = get_user_stats(user["id"])
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("📊 Total Queries",    stats.get("total_queries", 0) if stats.get("status") == "success" else "—")
    c2.metric("🔑 Plan",             user.get("role", "free").upper())
    rate_info = st.session_state.get("rate_info", {})
    used_today = rate_info.get("used") or rate_info.get("queries_today", "—")
    c3.metric("📅 Today's Queries",  used_today)
    c4.metric("🎯 Remaining Today",  rate_info.get("remaining", "—"))
    c5.metric("🌍 Markets Tracked",  len(records) if records else "—")

    st.markdown("---")

    if not records:
        st.info("📁 Dataset not loaded. Add `data/trade_map_2024.xls` to your project folder.")
        return

    data = get_dashboard_data(records)
    total_b = data["total_exports_usd_k"] / 1_000_000

    col1, col2 = st.columns([3, 2])
    with col1:
        df15 = pd.DataFrame([{
            "Country":        r["country"],
            "Export ($B)":    round(r["_export_value"] / 1_000_000, 2),
            "1yr Growth (%)": float(r["growth_1yr_pct"]) if r["growth_1yr_pct"] else 0,
        } for r in data["top15"]])
        fig = px.bar(df15, x="Export ($B)", y="Country", orientation="h",
                     color="1yr Growth (%)", color_continuous_scale="RdYlGn",
                     title="Top 15 Export Markets — India 2024")
        fig.update_layout(height=450, yaxis={"categoryorder": "total ascending"},
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                          font=dict(color="#c9d1d9"), margin=dict(t=40, b=8))
        st.plotly_chart(fig, use_container_width=True, config=_get_plotly_config())

    with col2:
        rd = {k: v for k, v in data["region_totals"].items() if v > 0}
        fig2 = px.pie(values=list(rd.values()), names=list(rd.keys()),
                      title="Exports by Region",
                      color_discrete_sequence=px.colors.qualitative.Set3, hole=0.38)
        fig2.update_traces(textposition="inside", textinfo="percent+label")
        fig2.update_layout(height=450, paper_bgcolor="rgba(0,0,0,0)",
                           font=dict(color="#c9d1d9"), margin=dict(t=40, b=8))
        st.plotly_chart(fig2, use_container_width=True, config=_get_plotly_config())

    st.markdown("---")

    # ── Quick actions ────────────────────────────────────────────
    st.markdown("#### ⚡ Quick Actions")
    qa_cols = st.columns(4)
    quick_actions = [
        ("🔍 New Trade Analysis",   "trade_analysis"),
        ("🤖 Ask TradeGPT",         "tradegpt"),
        ("🌍 Market Recommendations","market_recs"),
        ("📄 Analyze a Document",   "doc_analyzer"),
    ]
    for col, (label, page_key) in zip(qa_cols, quick_actions):
        with col:
            if st.button(label, use_container_width=True, key=f"qa_{page_key}"):
                st.session_state.active_page = page_key
                st.rerun()

# ════════════════════════════════════════════════════════════════════
# PAGE: TRADE ANALYSIS
# ════════════════════════════════════════════════════════════════════
def page_trade_analysis(records: list) -> None:
    user = st.session_state.user
    page_header("Trade Analysis", "Import duty, export policy & GST compliance — powered by Llama 3.3 70B", "🔍")

    if not _rate_guard():
        return

    # rate_info is for display only — enforcement is via consume_query() after AI call
    with st.container():
        col1, col2 = st.columns([3, 1])
        with col1:
            product = st.text_area(
                "📦 Product Description",
                placeholder="e.g. Organic turmeric powder, 95% curcumin, pharmaceutical grade, bulk 25kg HDPE bags...",
                height=110,
                help="Be specific: include grade, composition, packaging, end-use for best accuracy.",
            )
        with col2:
            mode = st.selectbox("Analysis Mode", ["Import", "Export", "Knowledge"],
                help="Import: duties & restrictions | Export: policy & incentives | Knowledge: GST & compliance")
            st.markdown("<br>", unsafe_allow_html=True)
            run = st.button("🚀 Analyze", use_container_width=True, type="primary")

    if run:
        if not product.strip():
            st.warning("⚠️ Please enter a product description.")
        else:
            with st.spinner("🤖 Analysing with Llama 3.3 70B..."):
                result = trade_intelligence_engine(product, mode)
            _consume_and_refresh(user["id"])
            log_trade_usage(user_id=user["id"], email=user["email"], mode=mode, product=product, result=result)
            ri = st.session_state.get("rate_info") or {}
            notify_user_limit_warning(user["id"], user["email"],
                                      (ri.get("queries_today") or ri.get("used", 0)),
                                      ri.get("daily_limit", ri.get("limit", 10)))
            if "error" in result:
                st.error(f"❌ {result['error']}")
                logger.error(f"Trade analysis error for user {user['email']}: {result['error']}")
            else:
                st.session_state.last_result  = result
                st.session_state.last_product = product
                st.session_state.last_mode    = mode

    # ── Render result from session_state (persists across reruns) ──
    if not st.session_state.last_result:
        return

    result  = st.session_state.last_result
    product = st.session_state.last_product
    mode    = st.session_state.last_mode

    conf = (result.get("data_confidence") or "medium").lower()
    conf_label = {"high": '<span class="conf-high">● High Confidence</span>',
                  "medium": '<span class="conf-med">● Medium Confidence</span>',
                  "low": '<span class="conf-low">● Low Confidence</span>'}.get(conf, '<span class="conf-med">● Medium Confidence</span>')
    st.markdown(f"### ✅ Analysis Complete &nbsp; {conf_label}", unsafe_allow_html=True)

    if result.get("validation_warning"):
        st.warning(f"⚠️ {result['validation_warning']}")

    if mode == "Import":
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("HS Code", result.get("hs_code", "N/A"))
        c2.metric("BCD", result.get("basic_customs_duty_percent", "N/A"))
        c3.metric("IGST", result.get("igst_percent", "N/A"))
        c4.metric("Total Landed Cost", result.get("total_landed_cost_percent", "N/A"))
        status = result.get("import_policy_status", "N/A")
        if status == "Free": st.success(f"**Import Status:** {status}  |  SWS: {result.get('social_welfare_surcharge_percent','N/A')}")
        elif status == "Restricted": st.warning(f"**Import Status:** {status}")
        else: st.error(f"**Import Status:** {status}")
        if result.get("license_required"):   st.warning("⚠️ Import licence required")
        if result.get("scomet_applicable"):  st.error("🚨 SCOMET controls applicable")
        if result.get("special_conditions"): st.info(f"**Special Conditions:** {result['special_conditions']}")

    elif mode == "Export":
        c1, c2, c3 = st.columns(3)
        c1.metric("HS Code", result.get("hs_code", "N/A"))
        c2.metric("Export Duty", result.get("export_duty_percent", "0%"))
        c3.metric("RoDTEP Rate", result.get("rodtep_rate_percent", "N/A"))
        status = result.get("export_policy_status", "N/A")
        if status == "Free": st.success(f"**Export Status:** {status}")
        elif status == "Restricted": st.warning(f"**Export Status:** {status}")
        else: st.error(f"**Export Status:** {status}")
        if result.get("rodtep_applicable"): st.success("✅ RoDTEP applicable")
        if result.get("rosctl_applicable"): st.success("✅ RoSCTL applicable")
        if result.get("export_incentive_notes"): st.info(f"**Incentives:** {result['export_incentive_notes']}")
        if result.get("documentation_required"):  st.info(f"**Documents:** {result['documentation_required']}")
        if result.get("restricted_countries") and result["restricted_countries"] not in ("none","None",""):
            st.warning(f"⚠️ **Country Restrictions:** {result['restricted_countries']}")

        if records:
            st.markdown("---")
            st.markdown("#### 🌍 Top 3 Export Markets for This Product")
            cols = st.columns(3)
            for i, (r, col) in enumerate(zip(get_top_markets(records, 3), cols)):
                val_str = f"${r['_export_value']/1_000_000:.1f}B"
                with col:
                    st.markdown(f"""
                    <div class="info-card">
                      <div style="font-weight:700;font-size:0.95rem;">{"🥇🥈🥉"[i]} {r['country']}</div>
                      <div style="color:#48bb78;font-size:1.3rem;font-weight:700;">{val_str}</div>
                      <div style="color:#6b7a99;font-size:0.78rem;margin-top:4px;">
                        1yr Growth: {r['growth_1yr_pct']}% · Score: {r['opportunity_score']}
                      </div>
                    </div>
                    """, unsafe_allow_html=True)

    else:  # Knowledge
        c1, c2, c3 = st.columns(3)
        c1.metric("HS Code", result.get("hs_code", "N/A"))
        c2.metric("GST Rate", result.get("gst_percent", "N/A"))
        c3.metric("GST Category", result.get("gst_category", "N/A"))
        if result.get("itc_available"): st.success(f"✅ ITC Available — {result.get('itc_conditions','')}")
        else: st.warning(f"⚠️ ITC Not Available — {result.get('itc_conditions','')}")
        rc = st.columns(3)
        if result.get("fssai_required"): rc[0].warning("⚠️ FSSAI Required")
        if result.get("bis_required"):   rc[1].warning("⚠️ BIS Required")
        if result.get("compliance_requirements"): st.info(f"**Compliance:** {result['compliance_requirements']}")
        if result.get("risk_flags") and result["risk_flags"] not in (None,"null","none","None",""): st.error(f"🚨 **Risk Flags:** {result['risk_flags']}")

    with st.expander("📋 Full JSON Response"):
        st.json(result)
    st.markdown("---")
    _download_row(result, product, mode, user["email"])

    st.markdown("---")
    st.markdown("#### 📊 Your Usage Stats")
    stats = get_user_stats(user["id"])
    if stats["status"] == "success":
        sc1, sc2, sc3, sc4, sc5 = st.columns(5)
        sc1.metric("Total Queries",    stats["total_queries"])
        sc2.metric("Total Logins",     stats["total_logins"])
        sc3.metric("Import",           stats["by_mode"].get("Import", 0))
        sc4.metric("Export",           stats["by_mode"].get("Export", 0))
        sc5.metric("Knowledge",        stats["by_mode"].get("Knowledge", 0))

# ════════════════════════════════════════════════════════════════════
# PAGE: DOCUMENT ANALYZER WITH OCR SCANNER
# ════════════════════════════════════════════════════════════════════
def page_document_analyzer() -> None:
    user      = st.session_state.user
    page_header("Document Analyzer", "AI-powered scanning, extraction & validation of trade documents", "📄")

    if not _rate_guard():
        return

    sub = st.tabs(["📋 Paste Text", "📤 Upload & Scan (OCR)"])

    # ── Tab 1: Paste text ────────────────────────────────────────
    with sub[0]:
        c1, c2 = st.columns([3, 1])
        with c1:
            doc_text = st.text_area(
                "Paste document text",
                height=200,
                placeholder="Paste a Commercial Invoice, Packing List, Bill of Lading, Shipping Bill, Letter of Credit...",
                key="doc_text_input",
            )
        with c2:
            doc_type = st.selectbox("Document Type", [
                "auto", "Commercial Invoice", "Packing List", "Bill of Lading",
                "Bill of Entry", "Shipping Bill", "Certificate of Origin", "Letter of Credit"
            ], key="doc_type_sel")
            st.markdown("<br>", unsafe_allow_html=True)
            run_doc = st.button("📄 Analyze", type="primary", use_container_width=True, key="doc_paste_btn")

        if run_doc:
            if not doc_text.strip():
                st.warning("Please paste document text.")
            else:
                with st.spinner("🤖 Extracting and validating..."):
                    result = analyze_trade_document(doc_text.strip(), doc_type)
                _consume_and_refresh(user["id"])
                log_trade_usage(user_id=user["id"], email=user["email"],
                                mode="Doc-Analyze", product=f"Document: {doc_type}", result=result)
                st.session_state.doc_result = result
                if "error" not in result:
                    st.rerun()

    # ── Tab 2: Upload & OCR ──────────────────────────────────────
    with sub[1]:
        st.markdown("""
        <div class="highlight-card" style="margin-bottom:16px;">
          <h4 style="color:#63b3ed;margin:0 0 6px;">🔍 Document Scanner Pipeline</h4>
          <p style="color:#8b949e;margin:0;font-size:0.85rem;">
            Upload trade documents (image PDFs, scanned PDFs, photos) → OCR extracts text → AI analyzes.<br>
            <strong>Multiple files supported</strong> — each file counts as 1 query.
          </p>
        </div>
        """, unsafe_allow_html=True)

        col1, col2 = st.columns([2, 1])
        with col1:
            uploaded_files = st.file_uploader(
                "Upload documents (multi-file supported)",
                type=["pdf", "png", "jpg", "jpeg"],
                accept_multiple_files=True,
                help="Supported: PDF (text or image/scanned), PNG, JPG, JPEG. Max 20MB each. Upload multiple files.",
                key="doc_upload",
            )
        with col2:
            ocr_doc_type = st.selectbox("Document Type", [
                "auto", "Commercial Invoice", "Packing List", "Bill of Lading",
                "Bill of Entry", "Shipping Bill", "Certificate of Origin", "Letter of Credit"
            ], key="ocr_doc_type")
            enhance = st.checkbox("🔧 Enhance image quality", value=True, help="Apply preprocessing to improve OCR accuracy on scanned documents")
            force_ocr = st.checkbox("🔄 Force OCR (skip text extraction)", value=False,
                                    help="Use for image-based PDFs where text layer is blank or garbled")
            st.markdown("<br>", unsafe_allow_html=True)
            run_ocr = st.button("🔍 Scan & Analyze", type="primary", use_container_width=True, key="doc_ocr_btn")

        if run_ocr:
            if not uploaded_files:
                st.warning("Please upload at least one document file.")
            else:
                all_doc_results = []
                combined_errors = []

                for uploaded_file in uploaded_files:
                    st.markdown(f"**Processing: {uploaded_file.name}**")
                    file_bytes = uploaded_file.read()

                    # Force OCR path: render PDF pages as images then OCR
                    if force_ocr and uploaded_file.name.lower().endswith(".pdf"):
                        with st.spinner(f"📖 Force-OCR: rendering {uploaded_file.name} as images..."):
                            scan_result = scan_document(file_bytes, uploaded_file.name,
                                                        enhance=enhance, force_ocr=True)
                    else:
                        with st.spinner(f"📖 Scanning {uploaded_file.name}..."):
                            scan_result = scan_document(file_bytes, uploaded_file.name, enhance=enhance)

                    if scan_result["status"] == "error":
                        msg = scan_result.get("message", "Unknown error")
                        st.error(f"❌ {uploaded_file.name}: {msg}")
                        is_tesseract = "Tesseract" in msg or "tesseract" in msg
                        if is_tesseract:
                            with st.expander("📋 How to fix — Tesseract Install Guide", expanded=True):
                                st.markdown("""
**`pip install pytesseract` only installs the Python wrapper — NOT the OCR engine.**

**Step 1 — Install Tesseract binary:**
- **🪟 Windows:** Download from [UB-Mannheim](https://github.com/UB-Mannheim/tesseract/wiki) → run `.exe` → tick **"Add to PATH"** → **close & reopen** terminal
- **🐧 Ubuntu/WSL:** `sudo apt-get install tesseract-ocr tesseract-ocr-eng`
- **🍎 macOS:** `brew install tesseract`

**Step 2 — Verify install:** `tesseract --version`

**Step 3 — If still failing on Windows** (PATH not updated), add to your `.env` file:
```
TESSERACT_CMD=C:\\Program Files\\Tesseract-OCR\\tesseract.exe
```
Then restart: `streamlit run app.py`

The app auto-detects Tesseract at: `C:\\Program Files\\Tesseract-OCR\\tesseract.exe`""")
                            break
                            break
                        elif scan_result.get("install_hint"):
                            st.info(scan_result["install_hint"])
                        combined_errors.append(uploaded_file.name)
                        continue

                    extracted_text = scan_result["text"]
                    st.success(f"✅ {uploaded_file.name}: {scan_result['char_count']:,} chars from {scan_result['pages']} page(s) via {scan_result.get('method','OCR')}")

                    with st.expander(f"👁️ Preview: {uploaded_file.name}"):
                        st.text_area("Extracted text (read-only)", value=extracted_text[:3000],
                                     height=150, disabled=True, key=f"ocr_prev_{uploaded_file.name}")

                    if extracted_text.strip():
                        with st.spinner(f"🤖 Analyzing {uploaded_file.name}..."):
                            doc_result = analyze_trade_document(extracted_text, ocr_doc_type)
                        _consume_and_refresh(user["id"])
                        log_trade_usage(user_id=user["id"], email=user["email"],
                                        mode="Doc-Scan-Analyze",
                                        product=f"Scanned: {uploaded_file.name}", result=doc_result)
                        doc_result["_filename"] = uploaded_file.name
                        all_doc_results.append(doc_result)
                    else:
                        st.warning(f"⚠️ {uploaded_file.name}: OCR produced empty text. Try 'Force OCR' option.")

                if all_doc_results:
                    # Store last result for shared display; if multiple files show a summary
                    st.session_state.doc_result = all_doc_results[-1]
                    if len(all_doc_results) > 1:
                        st.info(f"📋 Analyzed {len(all_doc_results)} documents. Showing last result below. "
                                f"Download each from the expanders above.")
                        for i, dr in enumerate(all_doc_results[:-1]):
                            fname = dr.get("_filename", f"Doc {i+1}")
                            with st.expander(f"📄 {fname} result"):
                                st.json(dr)
                    st.rerun()
                elif combined_errors:
                    st.error(f"All {len(combined_errors)} file(s) failed OCR extraction.")

    # ── Shared result display ────────────────────────────────────
    result = st.session_state.doc_result
    if not result:
        return
    if "error" in result:
        st.error(f"❌ {result['error']}")
        return

    st.markdown("---")
    status = result.get("compliance_status", "OK")
    if status == "OK":     st.success(f"✅ **{result.get('document_type','')}** · Status: {status}")
    elif status == "Review Needed": st.warning(f"⚠️ **{result.get('document_type','')}** · {status}")
    else:                  st.error(f"❌ **{result.get('document_type','')}** · {status}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Doc Number", result.get("document_number","—") or "—")
    c2.metric("Doc Date",   result.get("document_date","—")   or "—")
    c3.metric("Incoterm",   result.get("incoterm","—")         or "—")
    tv = result.get("total_invoice_value", {})
    c4.metric("Total Value", f"{tv.get('currency','USD')} {tv.get('amount',0):,.0f}")

    exp = result.get("exporter", {})
    imp = result.get("importer", {})
    if exp.get("name") or imp.get("name"):
        c1, c2 = st.columns(2)
        if exp.get("name"): c1.markdown(f"**Exporter:** {exp['name']}" + (f" · IEC: {exp['iec_code']}" if exp.get('iec_code') else ""))
        if imp.get("name"): c2.markdown(f"**Importer:** {imp['name']} · {imp.get('country','')}")

    products = result.get("products", [])
    if products:
        st.markdown("**Product Lines:**")
        df_data = [{
            "Line": p.get("line_no",""), "Description": p.get("description","")[:60],
            "HS Code": p.get("hs_code","—"), "✓": "✅" if p.get("hs_code_valid") else "⚠️",
            "Qty": f"{p.get('quantity','')} {p.get('unit','')}",
            "Unit Price": f"${p.get('unit_price_usd',0):,.2f}", "Total": f"${p.get('total_value_usd',0):,.2f}",
        } for p in products]
        st.dataframe(pd.DataFrame(df_data), use_container_width=True, hide_index=True)

    flags   = result.get("flags", [])
    missing = result.get("missing_critical_fields", [])
    if flags:   st.warning("**⚠️ Flags:**\n" + "\n".join(f"- {f}" for f in flags))
    if missing: st.error("**❌ Missing critical fields:**\n" + "\n".join(f"- {m}" for m in missing))
    if result.get("compliance_notes"): st.info(f"**Notes:** {result['compliance_notes']}")

    _download_row(result, ocr_doc_type if "ocr_doc_type" in locals() else "Document", "Doc-Analyze", user["email"])

# ════════════════════════════════════════════════════════════════════
# PAGE: PROFILE
# ════════════════════════════════════════════════════════════════════
def page_profile() -> None:
    user = st.session_state.user
    page_header("My Profile", "Account information, usage statistics, and session management", "👤")

    col1, col2 = st.columns([1, 2])
    with col1:
        st.markdown(f"""
        <div class="saas-card" style="text-align:center;">
          <div style="font-size:4rem;margin-bottom:12px;">👤</div>
          <h3 style="color:#e2e8f0;margin:0 0 4px;">{user['email'].split('@')[0]}</h3>
          <p style="color:#6b7a99;font-size:0.85rem;margin:0;">{user['email']}</p>
          <div style="margin-top:12px;">
            <span class="badge-info">{user.get('role','free').upper()}</span>
            {' <span class="badge-warning">ADMIN</span>' if user.get('is_admin') else ''}
          </div>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown("#### 📊 Usage Statistics")
        stats = get_user_stats(user["id"])
        if stats["status"] == "success":
            c1, c2 = st.columns(2)
            c1.metric("Total Queries",  stats["total_queries"])
            c2.metric("Total Logins",   stats["total_logins"])
            st.markdown("**Queries by mode:**")
            if stats["by_mode"]:
                df_mode = pd.DataFrame([{"Mode": k, "Count": v} for k, v in stats["by_mode"].items()])
                fig = px.bar(df_mode, x="Mode", y="Count", color="Mode",
                             color_discrete_sequence=px.colors.qualitative.Set2)
                fig.update_layout(height=200, showlegend=False, paper_bgcolor="rgba(0,0,0,0)",
                                  plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#c9d1d9"),
                                  margin=dict(t=10, b=10))
                st.plotly_chart(fig, use_container_width=True, config=_get_plotly_config())

        st.markdown("#### 🔐 Session")
        rate_info = st.session_state.get("rate_info", {})
        c1, c2 = st.columns(2)
        c1.metric("Plan Limit / Day", rate_info.get("daily_limit") or rate_info.get("limit", "—"))
        c2.metric("Used Today",       rate_info.get("used") or rate_info.get("queries_today", "—"))

        st.markdown("#### 🔑 Change Password")
        with st.form("change_pw_form"):
            new_pw  = st.text_input("New Password", type="password", placeholder="Min 6 characters")
            conf_pw = st.text_input("Confirm Password", type="password")
            ch_btn  = st.form_submit_button("Update Password", use_container_width=True, type="primary")
        if ch_btn:
            if not new_pw or not conf_pw: st.error("Fill in both fields.")
            elif new_pw != conf_pw: st.error("Passwords do not match.")
            elif len(new_pw) < 6: st.error("Password too short.")
            else:
                with st.spinner("Updating..."):
                    res = admin_update_user_password(user["email"], new_pw)
                if res["status"] == "success": st.success("✅ Password updated!")
                else: st.error(f"❌ {res['message']}")

# ════════════════════════════════════════════════════════════════════
# REMAINING PAGE FUNCTIONS (unchanged logic, updated visuals)
# ════════════════════════════════════════════════════════════════════

def page_market_recommendations(records: list) -> None:
    page_header("Market Recommendations", "Top export markets ranked by Opportunity Score", "🌍")
    if not records:
        st.warning("Dataset not loaded.")
        return
    c1, c2, c3 = st.columns(3)
    with c1: n       = st.slider("Markets to show", 3, 15, 5)
    with c2: min_val = st.selectbox("Min export size", ["Any","$100M+","$1B+","$5B+"])
    with c3: sort_by = st.selectbox("Sort by", ["Opportunity Score","Export Value","1yr Growth"])
    thresholds = {"$100M+": 100_000, "$1B+": 1_000_000, "$5B+": 5_000_000}
    filtered = [r for r in records if r["_export_value"] >= thresholds.get(min_val, 0)]
    top = get_top_markets(filtered, n=n)
    if sort_by == "Export Value":   top = sorted(top, key=lambda r: r["_export_value"], reverse=True)[:n]
    elif sort_by == "1yr Growth":   top = sorted(top, key=lambda r: float(r["growth_1yr_pct"] or 0), reverse=True)[:n]
    df = pd.DataFrame([{"Country": r["country"], "Export ($B)": round(r["_export_value"]/1_000_000,2),
                        "1yr Growth (%)": float(r["growth_1yr_pct"]) if r["growth_1yr_pct"] else 0,
                        "Opportunity Score": r["opportunity_score"]} for r in top])
    fig = px.bar(df, x="Country", y="Export ($B)", color="Opportunity Score",
                 color_continuous_scale="Viridis", title="Top Export Markets — India 2024", text="Export ($B)")
    fig.update_traces(texttemplate="%{text:.1f}B", textposition="outside")
    fig.update_layout(height=380, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font=dict(color="#c9d1d9"), margin=dict(t=40,b=8))
    st.plotly_chart(fig, use_container_width=True, config=_get_plotly_config())
    medals = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟","1️⃣1️⃣","1️⃣2️⃣","1️⃣3️⃣","1️⃣4️⃣","1️⃣5️⃣"]
    for i, r in enumerate(top):
        val     = r["_export_value"]
        val_str = f"${val/1_000_000:.1f}B" if val >= 1_000_000 else f"${val/1_000:.0f}M"
        bal     = r["_trade_balance"]
        bal_str = f"+${bal/1_000_000:.1f}B" if bal >= 0 else f"-${abs(bal)/1_000_000:.1f}B"
        with st.expander(f"{medals[i]} {r['country']}  —  Score: {r['opportunity_score']}", expanded=(i < 2)):
            cc1, cc2, cc3, cc4 = st.columns(4)
            cc1.metric("Export Value", val_str)
            cc2.metric("1yr Growth",   f"{r['growth_1yr_pct']}%" if r['growth_1yr_pct'] else "N/A")
            cc3.metric("India's Share",f"{r['india_share_partner_imports_pct']}%")
            cc4.metric("World Rank",   f"#{int(r['_world_rank'])}" if r['_world_rank'] else "N/A")
            st.caption(f"Trade Balance: {bal_str}  ·  5yr CAGR: {r['growth_5yr_pct']}%  ·  Distance: {r['avg_distance_km']} km")

def page_country_lookup(records: list) -> None:
    page_header("Country Trade Lookup", "India's detailed trade statistics with any country", "🔎")
    if not records:
        st.warning("Dataset not loaded.")
        return
    user      = st.session_state.user
    countries = sorted([r["country"] for r in records if r["_export_value"] > 0])
    default   = countries.index("United States of America") if "United States of America" in countries else 0
    selected  = st.selectbox("🌍 Select Country", countries, index=default)
    r = get_country_stats(records, selected)
    if not r:
        st.error(f"No data for '{selected}'")
        return
    log_market_lookup(None, user["id"], user["email"], selected)
    val     = r["_export_value"]
    val_str = f"${val/1_000_000:.2f}B" if val >= 1_000_000 else f"${val/1_000:.0f}M"
    bal     = r["_trade_balance"]
    bal_str = f"🟢 +${bal/1_000_000:.2f}B" if bal >= 0 else f"🔴 -${abs(bal)/1_000_000:.2f}B"
    st.markdown(f"### 🏳️ {selected}")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Export Value", val_str)
    c2.metric("Trade Balance", bal_str)
    c3.metric("India's Share", f"{r['india_share_partner_imports_pct']}%")
    c4.metric("1yr Growth", f"{r['growth_1yr_pct']}%" if r['growth_1yr_pct'] else "N/A")
    c5.metric("5yr CAGR", f"{r['growth_5yr_pct']}%" if r['growth_5yr_pct'] else "N/A")
    st.markdown("---")
    col1, col2 = st.columns(2)
    for col, score, title, bar_color in [
        (col1, r["opportunity_score"],  "Opportunity Score",  "#27AE60"),
        (col2, r["future_trend_score"], "Future Trend Score", "#2980B9"),
    ]:
        with col:
            fig = go.Figure(go.Indicator(
                mode="gauge+number", value=score,
                title={"text": title, "font": {"size":13,"color":"#c9d1d9"}},
                number={"font": {"color":"#e2e8f0"}},
                gauge={"axis":{"range":[0,100],"tickcolor":"#718096"},"bar":{"color":bar_color},
                       "bgcolor":"#161b22","steps":[{"range":[0,40],"color":"#1a0e0e"},
                       {"range":[40,70],"color":"#1a1a0e"},{"range":[70,100],"color":"#0e1a0e"}]},
            ))
            fig.update_layout(height=260, margin=dict(t=56,b=16,l=16,r=16), paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True, config=_get_plotly_config())

def page_future_trends(records: list) -> None:
    page_header("Future Export Trends", "Markets with highest 2–3 year growth potential", "🔮")
    if not records:
        st.warning("Dataset not loaded.")
        return
    trends = get_future_trends(records, n=15)
    df = pd.DataFrame([{"Country": r["country"], "Future Trend Score": r["future_trend_score"],
                        "Partner Growth 5yr%": float(r["partner_import_growth_5yr_pct"]) if r["partner_import_growth_5yr_pct"] else 0,
                        "India Share %": float(r["india_share_partner_imports_pct"]) if r["india_share_partner_imports_pct"] else 0,
                        "Export $B": round(r["_export_value"]/1_000_000,2)} for r in trends])
    fig = px.bar(df, x="Country", y="Future Trend Score", color="Partner Growth 5yr%",
                 color_continuous_scale="Plasma", title="Top 15 Markets by Future Potential",
                 hover_data=["India Share %","Export $B"])
    fig.update_layout(height=400, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font=dict(color="#c9d1d9"), margin=dict(t=40,b=8))
    st.plotly_chart(fig, use_container_width=True, config=_get_plotly_config())
    st.markdown("---")
    col1, col2 = st.columns(2)
    emerging = [r for r in trends if r["_india_share"] < 3 and r["_partner_growth"] > 5][:3]
    momentum = [r for r in trends if float(r["growth_5yr_pct"] or 0) > 10 and r["_export_value"] > 1_000_000][:3]
    with col1:
        st.markdown("**🌱 Emerging Opportunities** *(low India share, fast-growing)*")
        for r in emerging: st.info(f"**{r['country']}** — India share: {r['india_share_partner_imports_pct']}% · Market growth: {r['partner_import_growth_5yr_pct']}% p.a.")
    with col2:
        st.markdown("**🚀 Momentum Markets** *(India exports growing)*")
        for r in momentum: st.success(f"**{r['country']}** — ${r['_export_value']/1_000_000:.1f}B · 5yr CAGR: {r['growth_5yr_pct']}%")
    st.markdown("---")
    st.dataframe(df.set_index("Country"), use_container_width=True)

def page_hs_engine() -> None:
    user = st.session_state.user
    page_header("HS Code Engine", "AI-powered ITC-HS 2022 classification with duty lookup", "🔢")
    if not _rate_guard(): return
    sub = st.tabs(["🤖 AI Classify", "🔍 Direct Lookup"])
    with sub[0]:
        col1, col2 = st.columns([3, 1])
        with col1:
            product = st.text_area("📦 Product Description", placeholder="e.g. Organic turmeric, 95% curcumin, pharmaceutical grade", height=100, key="hs_product_input")
        with col2:
            st.markdown("<br>", unsafe_allow_html=True)
            run_hs = st.button("🔢 Classify", use_container_width=True, type="primary", key="hs_classify_btn")
        if run_hs and product.strip():
            with st.spinner("🤖 Classifying with Llama 3.3 70B + dataset lookup..."):
                result = classify_and_enrich(product.strip())
            _consume_and_refresh(user["id"])
            log_trade_usage(user_id=user["id"], email=user["email"], mode="HS-Classify", product=product.strip(), result=result)
            st.session_state.hs_result = result
            st.rerun()

        # ── Result (session_state, rendered every run) ──────────
        result = st.session_state.get("hs_result")
        if result:
            if "error" in result:
                st.error(f"❌ {result['error']}")
            else:
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("HS Code (8-digit)", result.get("hs_code","N/A"))
                c2.metric("BCD",   result.get("bcd", result.get("basic_customs_duty_percent","—")))
                c3.metric("IGST",  result.get("igst", result.get("igst_percent","—")))
                c4.metric("Total Import Burden", result.get("total_import_burden_pct","—"))
                st.markdown(f"**Chapter:** {result.get('chapter_no','')} — {result.get('chapter_name', result.get('chapter',''))}")
                st.markdown(f"**Description:** {result.get('hs_description', result.get('description',''))}")
                conf = result.get("confidence", 0)
                if conf: st.progress(float(conf), text=f"Classification confidence: {float(conf)*100:.0f}%")
                if result.get("classification_rationale"): st.info(f"**Rationale:** {result['classification_rationale']}")
                if result.get("validation_warning"):        st.warning(f"⚠️ {result['validation_warning']}")
                if result.get("scomet_restricted"):         st.error("🚨 SCOMET CONTROLLED — special licence required")
                c_link1, c_link2, c_link3 = st.columns(3)
                c_link1.markdown("🔗 [ICEGATE Tariff](https://www.icegate.gov.in)")
                c_link2.markdown("🔗 [DGFT Policy](https://www.dgft.gov.in)")
                c_link3.markdown("🔗 [GST Rates](https://cbic-gst.gov.in/gst-goods-services-rates.html)")
                with st.expander("📋 Full Classification Data"): st.json(result)
                _download_row(result, result.get("product","product"), "HS-Classify", user["email"])
    with sub[1]:
        hs_input = st.text_input("Enter HS Code (6 or 8 digits)", placeholder="09103010", key="hs_direct_input")
        col_btn, col_note = st.columns([1, 3])
        with col_btn:
            lookup_btn = st.button("🔍 Lookup", key="hs_direct_btn", use_container_width=True)
        with col_note:
            st.caption("Direct lookup from ITC-HS 2022 dataset — no AI, instant result")

        if lookup_btn and hs_input.strip():
            from hs_engine import lookup_hs_code
            r = lookup_hs_code(hs_input.strip())
            st.session_state.hs_direct_result = r
            st.session_state.hs_direct_code   = hs_input.strip()

        # ── Direct lookup result (session_state) ──
        r = st.session_state.get("hs_direct_result")
        if r:
            if r.get("error") or not r.get("hs_code"):
                st.warning(f"⚠️ HS code `{st.session_state.get('hs_direct_code','')}` not found in dataset. "
                           f"Try 6-digit or 8-digit ITC-HS code.")
                st.caption("Tip: Use AI Classify tab to find the HS code for a product by name.")
            else:
                st.success(f"✅ Found: **{r.get('hs_code','')}** — {r.get('description','')[:80]}")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("HS Code",  r.get("hs_code","—"))
                c2.metric("BCD",      r.get("bcd","—"))
                c3.metric("IGST",     r.get("igst","—"))
                c4.metric("GST Rate", r.get("gst_percent", r.get("rate","—")))
                if r.get("chapter_name"):   st.markdown(f"**Chapter:** {r.get('chapter_no','')} — {r['chapter_name']}")
                if r.get("description"):    st.info(r["description"])
                if r.get("scomet_restricted"): st.error("🚨 SCOMET CONTROLLED — special export licence required")
                if r.get("rodtep_rate"):    st.success(f"✅ RoDTEP Rate: {r['rodtep_rate']}")
                c_l1, c_l2 = st.columns(2)
                c_l1.markdown("🔗 [ICEGATE Tariff](https://www.icegate.gov.in)")
                c_l2.markdown("🔗 [DGFT FTP](https://www.dgft.gov.in)")
                with st.expander("📋 Full dataset record"): st.json(r)
                _download_row(r, r.get("hs_code","hs_direct"), "HS-Direct", user["email"])

def page_risk_analyzer() -> None:
    user = st.session_state.user
    page_header("Trade Risk Analyzer",
                "Score your trade risk across 6 dimensions — including geopolitical & sanctions",
                "⚠️")
    if not _rate_guard(): return

    c1, c2 = st.columns(2)
    with c1:
        product = st.text_input("📦 Product", placeholder="Basmati rice, Caustic Soda, Cotton yarn...", key="risk_product")
        origin_country = st.text_input("🏭 Origin Country (where produced)",
                                        placeholder="India", value="India", key="risk_origin")
    with c2:
        supplying_country = st.text_input("📤 Supplying Country (exporter)",
                                           placeholder="India (or supplier country)", value="India",
                                           key="risk_supplier")
        buyer_countries = st.text_input("🌍 Buyer / Destination Countries",
                                         placeholder="UAE, USA, Germany", key="risk_buyer")

    c3, c4 = st.columns(2)
    with c3:
        direction = st.selectbox("Trade Direction", ["Export", "Import"], key="risk_dir")
    with c4:
        val_usd = st.text_input("Shipment Value (USD)", value="50,000", key="risk_val")

    st.caption("💡 For best results: fill origin, supplier, and buyer countries. "
               "Risk analysis includes current geopolitical events (2024-2025).")

    if st.button("⚠️ Analyze Risk", type="primary", use_container_width=True, key="risk_btn"):
        if not product.strip() or not buyer_countries.strip():
            st.warning("Enter product and at least one buyer/destination country.")
        else:
            with st.spinner("🔍 Analyzing risk profile including geopolitical context..."):
                result = analyze_trade_risk(
                    product.strip(),
                    origin_country.strip() or "India",
                    supplying_country.strip() or "India",
                    buyer_countries.strip(),
                    direction,
                    val_usd,
                )
            _consume_and_refresh(user["id"])
            log_trade_usage(user_id=user["id"], email=user["email"],
                            mode="Risk", product=product.strip(), result=result)
            st.session_state.risk_result = result
            if "error" not in result:
                st.rerun()

    result = st.session_state.risk_result
    if not result:
        return
    if "error" in result:
        st.error(f"❌ {result['error']}")
        return

    # ── Geopolitical & mismatch alert banners ─────────────────────
    geo_alert = result.get("geopolitical_alert")
    if geo_alert and str(geo_alert).lower() not in ("null", "none", ""):
        st.warning(f"🌐 **Geopolitical Alert:** {geo_alert}")
    origin_risk = result.get("origin_supplying_mismatch_risk")
    if origin_risk and str(origin_risk).lower() not in ("null", "none", ""):
        st.error(f"⚠️ **Origin/Supplier Mismatch Risk:** {origin_risk}")

    # ── Overall score banner ───────────────────────────────────────
    score = result.get("overall_risk_score", 50)
    # Support both new schema (risk_level) and old (overall_risk_label)
    label = result.get("risk_level") or result.get("overall_risk_label", "Medium")
    level_colors = {"Low": "#48bb78", "Medium": "#ecc94b", "High": "#fc8181",
                    "Very High": "#e53e3e", "Critical": "#9b2c2c"}
    color = level_colors.get(label, "#ecc94b")
    # score is 0-100 in new schema, 0-10 in old — normalise for display
    score_display = f"{score}/100" if score > 10 else f"{score}/10"
    st.markdown(f"""<div class="saas-card" style="text-align:center;border-color:{color};">
      <div style="color:{color};font-size:2.5rem;font-weight:700;">{label} Risk</div>
      <div style="color:#a0aec0;font-size:1rem;">Overall Score: {score_display}</div>
    </div>""", unsafe_allow_html=True)

    # ── Executive summary ─────────────────────────────────────────
    summary = result.get("executive_summary", "")
    if summary:
        st.info(f"📋 **Summary:** {summary}")

    # ── Risk categories (new schema: list of dicts) ────────────────
    categories = result.get("risk_categories", [])
    if categories:
        st.markdown("#### 📊 Risk Breakdown")
        cat_icons = {
            "Regulatory & Sanctions": "📜",
            "Geopolitical Risk":      "🌐",
            "Currency & Payment":     "💱",
            "Logistics & Routing":    "🚢",
            "Market & Demand":        "📈",
            "Compliance & Documentation": "📋",
        }
        cols = st.columns(3)
        for i, cat in enumerate(categories):
            cat_name  = cat.get("category", f"Risk {i+1}")
            cat_score = cat.get("score", 50)
            cat_level = cat.get("level", "Medium")
            cat_icon  = cat_icons.get(cat_name, "⚠️")
            rc = level_colors.get(cat_level, "#ecc94b")
            # Normalise score for display
            cat_score_display = f"{cat_score}/100" if cat_score > 10 else f"{cat_score}/10"
            with cols[i % 3]:
                st.markdown(f"""<div class="info-card" style="text-align:center;margin-bottom:8px;">
                  <div style="font-size:0.78rem;color:#6b7a99;">{cat_icon} {cat_name}</div>
                  <div style="font-size:1.5rem;font-weight:700;color:{rc};">{cat_score_display}</div>
                  <div style="font-size:0.72rem;color:{rc};font-weight:600;">{cat_level}</div>
                </div>""", unsafe_allow_html=True)
        # Details + mitigation expanders
        for cat in categories:
            cat_name = cat.get("category", "Risk")
            details  = cat.get("details", "")
            mitig    = cat.get("mitigation", "")
            if details or mitig:
                with st.expander(f"{cat_icons.get(cat_name,'⚠️')} {cat_name} — Details & Mitigation"):
                    if details:
                        st.markdown(f"**Risk Details:** {details}")
                    if mitig:
                        st.markdown(f"**Mitigation:** {mitig}")
    else:
        # Old schema fallback: risk_dimensions dict
        dims = result.get("risk_dimensions", {})
        if dims:
            dim_labels = {
                "political_risk":   "🏛️ Political",
                "currency_risk":    "💱 Currency",
                "tariff_risk":      "📊 Tariff",
                "logistics_risk":   "🚢 Logistics",
                "compliance_risk":  "📋 Compliance",
                "payment_risk":     "💰 Payment",
            }
            cols = st.columns(3)
            for i, (key, lbl) in enumerate(dim_labels.items()):
                d = dims.get(key, {}); s = d.get("score", 5)
                rc = "#48bb78" if s <= 3 else ("#fc8181" if s > 6 else "#ecc94b")
                with cols[i % 3]:
                    st.markdown(f"""<div class="info-card" style="text-align:center;">
                      <div style="font-size:0.8rem;color:#6b7a99;">{lbl}</div>
                      <div style="font-size:1.6rem;font-weight:700;color:{rc};">{s}/10</div>
                      <div style="font-size:0.75rem;color:#4a5568;">{d.get('reason','')}</div>
                    </div>""", unsafe_allow_html=True)

    # ── Recommendations ───────────────────────────────────────────
    # Support both new (key_recommendations) and old (key_risks / risk_mitigation)
    recs = result.get("key_recommendations", [])
    key_risks = result.get("key_risks", [])
    risk_mitig = result.get("risk_mitigation", [])

    if recs:
        st.markdown("**✅ Key Recommendations**")
        for r in recs:
            st.markdown(f"- {r}")
    elif key_risks or risk_mitig:
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**🔴 Key Risks**")
            for r in key_risks: st.markdown(f"- {r}")
        with col2:
            st.markdown("**✅ Mitigation Strategies**")
            for m in risk_mitig: st.markdown(f"- {m}")

    # ── Payment & insurance advice ────────────────────────────────
    payment_adv = result.get("payment_terms_advice") or result.get("payment_recommendation", "")
    insurance   = result.get("insurance_suggestion", "")
    if payment_adv or insurance:
        c1, c2 = st.columns(2)
        if payment_adv:
            c1.info(f"**💳 Payment Advice:** {payment_adv}")
        if insurance:
            c2.info(f"**🛡️ Insurance:** {insurance}")

    # Old schema extras
    if result.get("recommended_incoterm"):
        st.info(f"**Incoterm:** {result.get('recommended_incoterm')}")
    if result.get("fta_applicable"):
        st.success(f"🤝 FTA Benefit: {result.get('fta_detail','')}")

    _download_row(result, product.strip() if product.strip() else "product", "Risk-Analysis", user["email"])

def page_price_intelligence() -> None:
    user = st.session_state.user
    page_header("Global Price Intelligence", "Benchmark your product price against global markets", "💰")
    if not _rate_guard(): return
    c1, c2, c3 = st.columns(3)
    with c1: product = st.text_input("📦 Product", placeholder="Turmeric powder", key="price_prod")
    with c2: qty     = st.text_input("Quantity Basis", value="1 MT", key="price_qty")
    with c3: market  = st.text_input("Target Market", value="Global", key="price_mkt")
    if st.button("💰 Get Price Intelligence", type="primary", use_container_width=True, key="price_btn"):
        if not product.strip(): st.warning("Enter a product.")
        else:
            with st.spinner("📊 Analyzing global prices..."):
                result = get_price_intelligence(product.strip(), qty, market)
            _consume_and_refresh(user["id"])
            log_trade_usage(user_id=user["id"], email=user["email"], mode="Price-Intel", product=product.strip(), result=result)
            st.session_state.price_result = result
            if "error" not in result:
                st.rerun()
    result = st.session_state.price_result
    if not result or "error" in result:
        if result and "error" in result: st.error(f"❌ {result['error']}")
        return
    fob = result.get("india_fob_price_usd",{}); dom = result.get("india_domestic_price_inr",{})
    lnd = result.get("target_market_landed_usd",{}); mgn = result.get("gross_margin_pct",{})
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("India FOB",          f"${fob.get('typical',0)} {fob.get('unit','')}")
    c2.metric("Domestic Price",     f"₹{dom.get('typical',0)} {dom.get('unit','')}")
    c3.metric("Market Landed",      f"${lnd.get('typical',0)} {lnd.get('unit','')}")
    c4.metric("Gross Margin",       f"{mgn.get('min',0)}–{mgn.get('max',0)}%")
    trend_color = {"Rising":"#48bb78","Falling":"#fc8181","Stable":"#ecc94b"}.get(result.get("global_price_trend","Stable"),"#a0aec0")
    st.markdown(f"""<div class="info-card"><span style="color:{trend_color};font-weight:700;">{result.get('global_price_trend','—')} Trend</span> — {result.get('trend_reason','')}</div>""", unsafe_allow_html=True)
    st.info(f"📌 **India's Position:** {result.get('india_price_advantage','')}")
    st.warning(f"⚠️ {result.get('data_note','Indicative ranges — verify with market quotes')}")
    _download_row(result, product if "product" in dir() else "product", "Price-Intel", user["email"])

def page_compliance_checker() -> None:
    user = st.session_state.user
    page_header("Trade Compliance Checker", "SCOMET controls, DGFT policy, licences & documentation", "📋")
    if not _rate_guard(): return
    c1, c2 = st.columns(2)
    with c1:
        product     = st.text_input("📦 Product", placeholder="Sodium cyanide 98%", key="comp_prod")
        hs_code     = st.text_input("HS Code (optional)", placeholder="28371100", key="comp_hs")
    with c2:
        origin      = st.text_input("Origin Country", value="India", key="comp_orig")
        destination = st.text_input("Destination Country", placeholder="Germany", key="comp_dest")
    direction = st.selectbox("Direction", ["Export","Import"], key="comp_dir")
    if st.button("📋 Check Compliance", type="primary", use_container_width=True, key="comp_btn"):
        if not product.strip() or not destination.strip(): st.warning("Enter product and destination.")
        else:
            with st.spinner("🔍 Running compliance checks..."):
                result = check_trade_compliance(product.strip(), hs_code.strip(), origin.strip(), destination.strip(), direction)
            _consume_and_refresh(user["id"])
            log_trade_usage(user_id=user["id"], email=user["email"], mode="Compliance", product=product.strip(), result=result)
            st.session_state.compliance_result = result
            if "error" not in result:
                st.rerun()
    result = st.session_state.compliance_result
    if not result or "error" in result:
        if result and "error" in result: st.error(f"❌ {result['error']}")
        return
    overall = result.get("overall_compliance_status","CLEAR")
    if overall == "CLEAR":       st.success(f"✅ **{overall}** — {result.get('compliance_summary','')}")
    elif overall == "CONDITIONAL": st.warning(f"⚠️ **{overall}** — {result.get('compliance_summary','')}")
    else:                         st.error(f"🚫 **{overall}** — {result.get('compliance_summary','')}")
    checks = result.get("checks",{})
    check_labels = {"scomet_control":"🔬 SCOMET","dgft_policy":"📜 DGFT","un_sanctions":"🌐 UN Sanctions",
                    "prohibited_items":"🚫 Prohibited","licence_required":"📄 Licence","quality_standards":"✅ Quality"}
    cols = st.columns(3)
    for i, (key, lbl) in enumerate(check_labels.items()):
        chk = checks.get(key,{}); s = chk.get("status","—")
        clr = "#48bb78" if s in ("CLEAR","NOT REQUIRED","OK") else ("#fc8181" if s=="BLOCKED" else "#ecc94b")
        with cols[i%3]:
            st.markdown(f"""<div class="info-card"><div style="font-weight:700;font-size:0.85rem;">{lbl}</div>
              <div style="color:{clr};font-weight:600;">{s}</div>
              <div style="font-size:0.75rem;color:#4a5568;">{chk.get('detail','')}</div></div>""", unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**📄 Required Documents**")
        for d in result.get("required_documents",[]): st.markdown(f"- {d}")
    with col2:
        st.markdown("**🔜 Next Steps**")
        for s in result.get("recommended_next_steps",[]): st.markdown(f"- {s}")
    _download_row(result, product if "product" in dir() else "product", "Compliance", user["email"])

def page_competitor_intelligence() -> None:
    user = st.session_state.user
    page_header("Competitor Intelligence", "Analyze India's global competition — know your rivals", "🥊")
    if not _rate_guard(): return
    c1, c2 = st.columns(2)
    with c1: product = st.text_input("📦 Product", placeholder="Basmati rice", key="comp_i_prod")
    with c2: market  = st.text_input("🌍 Target Market", placeholder="United States", key="comp_i_mkt")
    if st.button("🥊 Analyze Competition", type="primary", use_container_width=True, key="comp_i_btn"):
        if not product.strip() or not market.strip(): st.warning("Enter product and market.")
        else:
            with st.spinner("📊 Analyzing..."):
                result = get_competitor_intelligence(product.strip(), market.strip())
            _consume_and_refresh(user["id"])
            log_trade_usage(user_id=user["id"], email=user["email"], mode="Competitor-Intel", product=product.strip(), result=result)
            st.session_state.comp_result = result
            if "error" not in result:
                st.rerun()
    result = st.session_state.comp_result
    if not result or "error" in result:
        if result and "error" in result: st.error(f"❌ {result['error']}")
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("India's Share", f"{result.get('india_market_share_pct', result.get('india_current_market_share_pct',0))}%")
    c2.metric("India's Rank",  f"#{result.get('india_rank', result.get('india_rank_in_market',0))}")
    c3.metric("Market Size",   f"${result.get('market_total_imports_usd_m',0)}M")
    c4.metric("Entry Difficulty", result.get("market_entry_difficulty","Medium"))
    competitors = result.get("top_competitors",[])
    if competitors:
        df = pd.DataFrame([{"Country": c.get("country",""), "Rank": c.get("rank",""),
                            "Market Share": f"{c.get('share_pct',c.get('market_share_pct',0))}%",
                            "Price Level": c.get("price_level",""),
                            "India vs": c.get("india_vs_this_competitor",c.get("india_vs_competitor",""))[:80]} for c in competitors])
        st.dataframe(df, use_container_width=True, hide_index=True)
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**✅ India's Strengths**")
        for s in result.get("india_strengths",[]): st.markdown(f"- {s}")
    with col2:
        st.markdown("**⚠️ India's Weaknesses**")
        for w in result.get("india_weaknesses",[]): st.markdown(f"- {w}")
    st.info(f"**🎯 Win Strategy:** {result.get('differentiation_strategy','')}")
    _download_row(result, product if "product" in dir() else "product", "Competitor-Intel", user["email"])

def page_smart_trade_ideas() -> None:
    user = st.session_state.user
    page_header("Smart Trade Ideas", "5 tailored AI-generated import/export business opportunities", "💡")
    if not _rate_guard(): return
    c1, c2, c3 = st.columns(3)
    with c1: budget    = st.selectbox("Budget", ["Under 5 lakhs","5-10 lakhs","10-50 lakhs","50L-1 Cr","1 Cr+"], index=2, key="idea_budget")
    with c2: direction = st.selectbox("Direction", ["Export","Import","Both"], key="idea_dir")
    with c3: industry  = st.selectbox("Industry", ["Any","Agriculture/Food","Textiles","Chemicals","Engineering","Handicrafts","Pharma","Technology"], key="idea_ind")
    profile = st.text_area("Tell us about yourself (optional)", placeholder="e.g. I'm in Gujarat, have a textile unit, looking for export opportunities...", height=80, key="idea_profile")
    if st.button("💡 Generate Ideas", type="primary", use_container_width=True, key="ideas_btn"):
        with st.spinner("🤖 Generating tailored opportunities..."):
            result = generate_smart_trade_ideas(
                profile.strip() or "Indian entrepreneur, open to opportunities",
                budget, direction, industry
            )
        # Always consume and log (even on error — query was used)
        _consume_and_refresh(user["id"])
        log_trade_usage(user_id=user["id"], email=user["email"], mode="Trade-Ideas", product="Smart Ideas", result=result)
        st.session_state.ideas_result = result
        if "error" not in result:
            st.rerun()
    result = st.session_state.ideas_result
    if not result:
        return
    if "error" in result:
        st.error(f"❌ {result['error']}")
        return
    if result.get("profile_analysis"): st.info(f"**AI Assessment:** {result['profile_analysis']}")
    for idea in result.get("ideas",[]):
        with st.expander(f"#{idea.get('rank','')} — {idea.get('title','')}  |  Margin: {idea.get('typical_margin_pct','')}  |  {idea.get('difficulty_level','')}", expanded=(idea.get('rank') == result.get("most_recommended",1))):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Product",    idea.get("product","")[:30])
            c2.metric("HS Range",   idea.get("hs_code_range",""))
            c3.metric("Investment", f"₹{idea.get('initial_investment_inr','')}")
            c4.metric("Revenue/mo", f"₹{idea.get('monthly_revenue_potential_inr','')}")
            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f"**Markets:** {', '.join(idea.get('target_markets',[]))}")
                st.markdown(f"**Schemes:** {', '.join(idea.get('relevant_schemes',[]))}")
            with c2:
                st.markdown(f"**Why Now:** {idea.get('why_now','')}")
                st.markdown(f"**India Advantage:** {idea.get('india_advantage','')}")
            st.warning(f"**⚠️ Challenge:** {idea.get('key_challenge','')}")
            st.success(f"**✅ First Step:** {idea.get('first_step','')}")
    _download_row(result, "Smart Trade Ideas", "Ideas", user["email"])

def page_supplier_finder() -> None:
    user = st.session_state.user
    page_header("Global Supplier Finder", "Find and evaluate global sourcing options for any import", "🔗")
    if not _rate_guard(): return
    c1, c2, c3, c4 = st.columns(4)
    with c1: product  = st.text_input("📦 Product to Import", placeholder="Industrial bearings", key="sup_prod")
    with c2: qty      = st.text_input("Quantity Required", placeholder="5 MT", key="sup_qty")
    with c3: quality  = st.selectbox("Quality Standard", ["Standard","ISO 9001","CE Mark","FDA","Premium","Budget"], key="sup_qual")
    with c4: origin   = st.text_input("Preferred Origin", value="Any", key="sup_orig")
    if st.button("🔗 Find Suppliers", type="primary", use_container_width=True, key="sup_btn"):
        if not product.strip(): st.warning("Enter a product.")
        else:
            with st.spinner("🌍 Analyzing global supply chain..."):
                result = find_global_suppliers(product.strip(), qty.strip() or "1 MT", quality, origin.strip())
            _consume_and_refresh(user["id"])
            log_trade_usage(user_id=user["id"], email=user["email"], mode="Supplier-Finder", product=product.strip(), result=result)
            st.session_state.supplier_result = result
            if "error" not in result:
                st.rerun()
    result = st.session_state.supplier_result
    if not result or "error" in result:
        if result and "error" in result: st.error(f"❌ {result['error']}")
        return
    st.info(f"**Global Supply:** {result.get('global_supply_overview','')}")
    for i, o in enumerate(result.get("top_supply_origins",[])):
        medal = ["🥇","🥈","🥉","4️⃣","5️⃣"][min(i,4)]
        with st.expander(f"{medal} {o.get('country','')} — {o.get('fob_price_range_usd','')} | Quality: {o.get('quality_level','')}", expanded=(i==0)):
            c1, c2, c3 = st.columns(3)
            c1.metric("Min Order",  o.get("min_order_qty",""))
            c2.metric("Lead Time",  f"{o.get('lead_time_weeks','')} weeks")
            c3.metric("Landed Markup", o.get("total_landed_markup_pct",o.get("total_landed_cost_markup_pct","")))
            st.markdown(f"**BCD:** {o.get('bcd_pct',o.get('india_import_duty_bcd_pct',''))}  ·  **IGST:** {o.get('igst_pct',o.get('india_igst_pct',''))}")
            if o.get("fta_with_india"): st.success(f"✅ FTA with India — Duty saving: {o.get('fta_saving',o.get('fta_duty_saving',''))}")
            if o.get("concerns"):       st.warning("⚠️ Watch out: " + ", ".join(o["concerns"]))
    _download_row(result, product if "product" in dir() else "product", "Supplier-Finder", user["email"])

def page_shipment_calculator() -> None:
    user = st.session_state.user
    page_header("Shipment Cost Calculator", "Complete export/import cost — freight, duties, port charges", "🚢")
    if not _rate_guard(): return
    c1, c2, c3 = st.columns(3)
    with c1:
        product = st.text_input("📦 Product", placeholder="Basmati rice", key="ship_prod")
        hs_code = st.text_input("HS Code (optional)", placeholder="10063020", key="ship_hs")
    with c2:
        origin_port      = st.selectbox("Origin Port", ["JNPT (Mumbai)","Mundra (Gujarat)","Chennai","Nhava Sheva","Kolkata","Vizag","Cochin","Delhi ICD","Other"], key="ship_origin")
        destination_port = st.text_input("Destination Port", placeholder="Port of Rotterdam", key="ship_dest")
    with c3:
        weight    = st.number_input("Weight (kg)",       min_value=1.0,   value=1000.0, step=100.0, key="ship_wt")
        volume    = st.number_input("Volume (CBM)",      min_value=0.1,   value=5.0,    step=0.5,   key="ship_vol")
        cargo_val = st.number_input("Cargo Value (USD)", min_value=100.0, value=10000.0,step=500.0, key="ship_val")
    direction = st.selectbox("Direction", ["Export","Import"], key="ship_dir")
    if st.button("🚢 Calculate", type="primary", use_container_width=True, key="ship_btn"):
        if not product.strip() or not destination_port.strip():
            st.warning("Enter product and destination.")
        else:
            with st.spinner("📊 Calculating..."):
                result = calculate_shipment_cost(
                    product.strip(), hs_code.strip(), origin_port,
                    destination_port.strip(), weight, volume, cargo_val, direction
                )
            _consume_and_refresh(user["id"])
            log_trade_usage(user_id=user["id"], email=user["email"],
                            mode="Shipment-Calc", product=product.strip(), result=result)
            st.session_state.ship_result = result
            st.rerun()

    # ── Result (rendered every run from session_state) ──────────
    result = st.session_state.get("ship_result")
    if not result:
        return
    if "error" in result:
        st.error(f"❌ {result['error']}")
        return
    frt  = result.get("freight_charges",{})
    orig = result.get("origin_charges",{})
    ins  = result.get("insurance",{})
    summ = result.get("total_cost_summary",{})
    c1, c2, c3 = st.columns(3)
    c1.metric("Sea Freight",        f"${frt.get('sea_freight_usd',0):,.0f}")
    c2.metric("Total Origin (INR)", f"₹{orig.get('total_origin_inr',0):,.0f}")
    c3.metric("Insurance",          f"${ins.get('premium_usd',0):,.0f}")
    st.success(f"**Recommended Mode:** {frt.get('recommended_mode','Sea')} — {frt.get('mode_reason','')}")
    c1, c2 = st.columns(2)
    c1.metric("Export Cost (INR)",        f"₹{summ.get('export_cost_inr_approx',0):,.0f}")
    c2.metric("Import Landed Cost (USD)", f"${summ.get('import_landed_cost_usd',0):,.0f}")
    st.info(f"Total landed ≈ **{summ.get('cost_as_pct_cargo_value','—')}** of cargo value")
    transit = result.get("transit_time_days",{})
    if transit:
        st.caption(f"⏱ Transit: Sea {transit.get('sea','')} days  ·  Air {transit.get('air','')} days")
    if result.get("notes"): st.info(f"💡 {result['notes']}")
    _download_row(result, product if "product" in dir() else "product", "Shipment-Calc", user["email"])

def page_tradegpt() -> None:
    user = st.session_state.user
    page_header("TradeGPT", "Your AI trade advisor — ask anything about Indian and global trade", "🤖")
    if not _rate_guard(): return
    starters = [
        "What is the RoDTEP rate for organic turmeric export?",
        "How do I get an Import Export Code (IEC)?",
        "What documents are needed to export to UAE under CEPA?",
        "Explain the difference between FOB and CIF Incoterms",
        "What is ECGC and how does it protect exporters?",
    ]
    st.caption("**Quick start questions:**")
    cols = st.columns(len(starters))
    for i, q in enumerate(starters):
        if cols[i].button(q[:38]+"..." if len(q) > 38 else q, key=f"starter_{i}"):
            st.session_state.chat_history.append({"role":"user","content":q})
            with st.spinner("TradeGPT thinking..."):
                resp = chat_with_tradegpt(q, st.session_state.chat_history[:-1], st.session_state.get("chat_context"))
                st.session_state.chat_history.append({"role":"assistant","content":resp.get("reply","")})
                _consume_and_refresh(user["id"])
                log_trade_usage(user_id=user["id"], email=user["email"], mode="TradeGPT", product=q[:100], result=resp)
    st.markdown("---")
    for msg in st.session_state.chat_history:
        if msg["role"] == "user":
            st.markdown(f"""<div style="background:#0d1627;border:1px solid #1e2d45;border-radius:10px;
                        padding:12px 16px;margin:6px 0;text-align:right;">
              <span style="color:#e2e8f0;">{msg['content']}</span></div>""", unsafe_allow_html=True)
        else:
            st.markdown(f"""<div style="background:#0a1a35;border:1px solid #1a6fa8;border-radius:10px;
                        padding:12px 16px;margin:6px 0;">
              <span style="color:#63b3ed;font-size:0.78rem;font-weight:600;">🤖 TradeGPT</span><br>
              <span style="color:#e2e8f0;">{msg['content'].replace(chr(10),'<br>')}</span></div>""", unsafe_allow_html=True)
    user_msg = st.text_input("💬 Ask TradeGPT anything...", placeholder="What export incentives are available for spice exporters?", key="chat_input")
    c1, c2 = st.columns([5, 1])
    with c2:
        if st.button("Send →", type="primary", use_container_width=True, key="chat_send"):
            if user_msg.strip():
                st.session_state.chat_history.append({"role":"user","content":user_msg.strip()})
                with st.spinner("Thinking..."):
                    resp = chat_with_tradegpt(user_msg.strip(), st.session_state.chat_history[:-1], st.session_state.get("chat_context"))
                    st.session_state.chat_history.append({"role":"assistant","content":resp.get("reply","")})
                    _consume_and_refresh(user["id"])
                    log_trade_usage(user_id=user["id"], email=user["email"], mode="TradeGPT", product=user_msg[:100], result=resp)
                    if resp.get("follow_up_questions"): st.session_state["_chat_followups"] = resp["follow_up_questions"]
                st.rerun()
    if st.session_state.chat_history:
        if st.button("🗑️ Clear Chat", key="chat_clear"):
            st.session_state.chat_history = []
            st.session_state.pop("_chat_followups", None)
            st.rerun()

def page_ai_reports() -> None:
    user = st.session_state.user
    page_header("AI Trade Reports", "Full trade feasibility reports with executive summary & 90-day action plan", "📊")
    if not _rate_guard(): return
    c1, c2 = st.columns(2)
    with c1:
        product   = st.text_input("📦 Product", placeholder="Organic turmeric powder", key="rpt_prod")
        direction = st.selectbox("Direction", ["Export","Import"], key="rpt_dir")
    with c2:
        countries_raw = st.text_input("Target Markets (comma-separated)", placeholder="USA, Germany, UAE", key="rpt_countries")
    if st.button("📊 Generate Report", type="primary", use_container_width=True, key="rpt_btn"):
        if not product.strip(): st.warning("Enter a product.")
        else:
            countries = [c.strip() for c in countries_raw.split(",") if c.strip()] or ["USA","UAE","Germany"]
            with st.spinner(f"🤖 Generating comprehensive {direction} report..."):
                result = generate_ai_trade_report(product.strip(), direction, countries)
            _consume_and_refresh(user["id"])
            log_trade_usage(user_id=user["id"], email=user["email"], mode="Trade-Report", product=product.strip(), result=result)
            st.session_state.report_result = result
            if "error" not in result:
                st.rerun()
    result = st.session_state.report_result
    if not result or "error" in result:
        if result and "error" in result: st.error(f"❌ {result['error']}")
        return
    st.markdown(f"## 📊 {result.get('report_title','Trade Report')}")
    es = result.get("executive_summary",{})
    if es:
        st.markdown("### 📌 Executive Summary")
        c1, c2 = st.columns(2)
        c1.success(f"**Key Finding:** {es.get('headline_finding','')}")
        c2.info(f"**Opportunity:** {es.get('market_opportunity','')}")
        st.markdown(f"**Recommendation:** {es.get('top_recommendation','')}")
        if es.get("key_risks"): st.warning("**Key Risks:** " + " | ".join(es["key_risks"]))
    markets = result.get("market_analysis",[])
    if markets:
        st.markdown("### 🌍 Market Analysis")
        df = pd.DataFrame([{"Country": m.get("country",""), "Import $M": m.get("import_size_usd_m",0),
                            "India Share %": m.get("india_share_pct",0), "Growth %": m.get("growth_rate_pct",0),
                            "Score": m.get("opportunity_score",0), "Entry": m.get("entry_difficulty",""),
                            "Tariff %": m.get("tariff_pct",0), "FTA": m.get("fta_benefit","N/A")} for m in markets])
        st.dataframe(df, use_container_width=True, hide_index=True)
    ap = result.get("action_plan",[])
    if ap:
        st.markdown("### 📅 90-Day Action Plan")
        for step in ap: st.markdown(f"**Week {step.get('week','')}:** {step.get('action','')} → *{step.get('output','')}*")
    with st.expander("📋 Full Report JSON"): st.json(result)
    _download_row(result, product if "product" in dir() else "product", "Trade-Report", user["email"])

def page_support() -> None:
    user  = st.session_state.user
    uid   = user["id"]
    email = user["email"]
    page_header("Support Center", "Contact support · Report AI errors · Request features", "🎫")
    sub_tabs = st.tabs(["💬 Contact Support","🐛 Report AI Error","💡 Feature Request","📂 My Tickets"])

    with sub_tabs[0]:
        st.markdown("#### 💬 Contact Support")
        with st.form("support_contact_form", clear_on_submit=True):
            cs_subject  = st.text_input("Subject *", placeholder="e.g. Cannot access my account", max_chars=200)
            cs_priority = st.selectbox("Priority", ["low","medium","high"], index=1, format_func=lambda x: PRIORITY_LABELS[x])
            cs_desc     = st.text_area("Describe your issue *", height=160, max_chars=4000)
            cs_sub      = st.form_submit_button("📨 Submit Ticket", use_container_width=True, type="primary")
        if cs_sub:
            if not cs_subject.strip() or not cs_desc.strip(): st.error("Fill in Subject and Description.")
            else:
                res = submit_ticket(user_id=uid, email=email, ticket_type="contact_support",
                                    subject=cs_subject.strip(), description=cs_desc.strip(), priority=cs_priority)
                if res["status"] == "success": st.success(f"✅ Ticket **#{res['ticket_id']}** submitted!"); st.balloons()
                else: st.error(f"❌ {res['message']}")

    with sub_tabs[1]:
        st.markdown("#### 🐛 Report an AI Error")
        with st.form("support_ai_error_form", clear_on_submit=True):
            ae_subject    = st.text_input("What was wrong? *", placeholder="e.g. Wrong HS code for turmeric", max_chars=200)
            ae_product    = st.text_input("Product queried", max_chars=300)
            ae_mode       = st.selectbox("Query mode", ["Import","Export","Knowledge"])
            ae_ai_output  = st.text_area("AI's response (incorrect part) *", height=130, max_chars=3000)
            ae_correct    = st.text_area("Correct answer (if known)", height=90, max_chars=2000)
            ae_priority   = st.selectbox("Severity", ["low","medium","high"], index=1, format_func=lambda x: PRIORITY_LABELS[x])
            ae_sub        = st.form_submit_button("🐛 Submit Error Report", use_container_width=True, type="primary")
        if ae_sub:
            if not ae_subject.strip() or not ae_ai_output.strip(): st.error("Fill in Subject and AI response.")
            else:
                full_desc = f"**Product:** {ae_product or 'N/A'}\n**Mode:** {ae_mode}\n\n**AI output:**\n{ae_ai_output.strip()}\n\n**Correct:**\n{ae_correct.strip() or 'Not provided'}"
                res = submit_ticket(user_id=uid, email=email, ticket_type="report_ai_error",
                                    subject=ae_subject.strip(), description=full_desc, priority=ae_priority)
                if res["status"] == "success": st.success(f"✅ Report **#{res['ticket_id']}** submitted!"); st.balloons()
                else: st.error(f"❌ {res['message']}")

    with sub_tabs[2]:
        st.markdown("#### 💡 Feature Request")
        with st.form("support_feature_form", clear_on_submit=True):
            fr_subject  = st.text_input("Feature title *", placeholder="e.g. Add MEIS/RoDTEP rate calculator", max_chars=200)
            fr_category = st.selectbox("Category", ["Trade Analysis Improvement","New Data / Dataset","UI / UX Improvement","Export / Reports","Integration","Admin / User Management","Other"])
            fr_desc     = st.text_area("Describe the feature *", height=160, max_chars=4000)
            fr_priority = st.selectbox("Importance", ["low","medium","high"], index=1, format_func=lambda x: {"low":"Nice to have","medium":"Important","high":"Critical"}[x])
            fr_sub      = st.form_submit_button("💡 Submit Request", use_container_width=True, type="primary")
        if fr_sub:
            if not fr_subject.strip() or not fr_desc.strip(): st.error("Fill in title and description.")
            else:
                res = submit_ticket(user_id=uid, email=email, ticket_type="feature_request",
                                    subject=fr_subject.strip(), description=f"**Category:** {fr_category}\n\n{fr_desc.strip()}", priority=fr_priority)
                if res["status"] == "success": st.success(f"✅ Request **#{res['ticket_id']}** submitted!"); st.balloons()
                else: st.error(f"❌ {res['message']}")

    with sub_tabs[3]:
        st.markdown("#### 📂 My Support Tickets")
        tickets, _err = get_user_tickets(uid)
        if _err: st.error(f"❌ {_err}")
        elif not tickets:
            st.info("📭 You haven't submitted any tickets yet.")
        else:
            for tkt in tickets:
                _s_lbl = STATUS_LABELS.get(tkt.get("status","open"),"open")
                _type  = TICKET_TYPES.get(tkt.get("ticket_type",""),"Support")
                with st.expander(f"{_s_lbl} · {_type} — **{tkt.get('subject','')[:55]}** ({(tkt.get('created_at') or '')[:10]})"):
                    st.markdown(f"**Status:** {_s_lbl}  ·  **Priority:** {PRIORITY_LABELS.get(tkt.get('priority','medium'),'')}")
                    if tkt.get("admin_note"):
                        st.markdown(f"<div style='background:#1a2a1a;border:1px solid #27ae60;border-radius:8px;padding:12px;margin-top:10px;font-size:0.85rem;color:#48bb78;'>📝 <strong>Admin response:</strong><br>{tkt['admin_note']}</div>", unsafe_allow_html=True)
                    else: st.caption("⏳ Awaiting admin response.")

def page_data_sync(records: list) -> None:
    from supabase_service import supabase as _sb
    if not st.session_state.user.get("is_admin", False):
        st.error("🚫 Access denied.")
        return
    page_header("Data Sync", "Upload trade dataset to Supabase and notify users", "💾")
    c1, c2 = st.columns(2)
    c1.metric("Records ready", len(records))
    c2.metric("Status", "✅ Synced" if st.session_state.db_uploaded else "⏳ Not synced")
    if not records: st.warning("Dataset not found at `data/trade_map_2024.xls`."); return
    if st.button("🚀 Upload to Supabase", type="primary", use_container_width=True):
        with st.spinner(f"Uploading {len(records)} records..."):
            res = upload_trade_data_to_supabase(records, _sb)
        if res["status"] == "success":
            st.success(f"✅ {res['rows_uploaded']} records uploaded!")
            st.session_state.db_uploaded = True
            st.balloons()
        else:
            st.error(f"❌ {res['message']}")
    st.markdown("---")
    st.markdown("### 📧 Notify All Users")
    ds_name = st.text_input("Dataset label", value="Trade Map 2024 (Updated)", max_chars=80)
    import re as _re
    _url_pat = _re.compile(r"https?://|www\.|\.com|\.in", _re.I)
    _blocked = _url_pat.search(ds_name.strip())
    if _blocked: st.error("❌ Label must not contain URLs.")
    elif st.button("📨 Send Email Alert", use_container_width=True):
        with st.spinner("Sending..."):
            res = notify_all_users_new_dataset(ds_name.strip())
        if res["status"] == "success": st.success(f"✅ Sent to {res['sent']} users")
        else: st.error(f"❌ {res['message']}")

# ════════════════════════════════════════════════════════════════════
# MAIN ROUTER
# ════════════════════════════════════════════════════════════════════
def main() -> None:
    if not st.session_state.user:
        login_page()
        return

    # ── Post-confirmation welcome banner (shown once after email confirm) ──
    if st.session_state.get("just_confirmed"):
        st.session_state.pop("just_confirmed", None)
        user_email = st.session_state.user.get("email", "")
        st.success(f"🎉 Welcome to the Indian Trade Intelligence Engine, **{user_email}**! Your account is active.")
        st.balloons()

    # Sidebar returns active page
    active_page = render_sidebar(st.session_state.user)
    records = get_trade_data()

    # Guard admin-only pages
    is_admin = st.session_state.user.get("is_admin", False)

    page_dispatch = {
        "dashboard":      lambda: page_dashboard(records),
        "trade_analysis": lambda: page_trade_analysis(records),
        "hs_engine":      page_hs_engine,
        "market_recs":    lambda: page_market_recommendations(records),
        "country_lookup": lambda: page_country_lookup(records),
        "future_trends":  lambda: page_future_trends(records),
        "tradegpt":       page_tradegpt,
        "risk":           page_risk_analyzer,
        "price_intel":    page_price_intelligence,
        "competitor":     page_competitor_intelligence,
        "trade_ideas":    page_smart_trade_ideas,
        "ai_reports":     page_ai_reports,
        "suppliers":      page_supplier_finder,
        "shipment":       page_shipment_calculator,
        "doc_analyzer":   page_document_analyzer,
        "compliance":     page_compliance_checker,
        "support":        page_support,
        "profile":        page_profile,
        "data_sync":      lambda: page_data_sync(records),
        "admin":          render_admin_dashboard,
    }

    fn = page_dispatch.get(active_page)
    if fn:
        fn()
    else:
        page_dashboard(records)

if __name__ == "__main__":
    main()