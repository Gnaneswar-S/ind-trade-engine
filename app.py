"""
app.py
🇮🇳 Indian Trade Intelligence Engine
──────────────────────────────────────────────────────────────
Features:
  Auth   — Login · Register · Forgot Password · Email Confirmation
  2FA    — Optional OTP via email (otp_service.py)
  Trades — Import / Export / Knowledge analysis (Llama 3.3 70B)
  Data   — Market Recommendations · Country Lookup · Dashboard · Future Trends
  Export — Download report as Excel / PDF / JSON (report_service.py)
  Admin  — Full dashboard, role management (admin_dashboard.py)
  Limits — Per-role daily rate limiting with live progress bar
──────────────────────────────────────────────────────────────
"""

import os
import json as _json
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

from gemini_service import trade_intelligence_engine
from trade_advisor import (
    chat_with_tradegpt,
    analyze_trade_risk,
    get_price_intelligence,
    analyze_trade_document,
    check_trade_compliance,
    get_competitor_intelligence,
    generate_smart_trade_ideas,
    find_global_suppliers,
    generate_ai_trade_report,
)
from hs_engine import classify_and_enrich, calculate_shipment_cost, get_dataset_status
from supabase_service import (
    sign_up_user, login_user, login_with_token, logout_user,
    log_trade_usage, get_user_stats, check_rate_limit,
    notify_all_users_new_dataset, notify_user_limit_warning,
    request_password_reset, verify_reset_otp, admin_update_user_password, smtp_diagnostic,
    exchange_code_for_session, update_user_password,
    get_platform_stats, get_all_users, get_all_queries, update_user_role,
)
from trade_data_service import (
    load_trade_data, get_top_markets, get_future_trends,
    get_country_stats, get_dashboard_data,
    upload_trade_data_to_supabase, log_market_lookup,
)
from otp_service     import send_otp_email, verify_otp
from report_service  import export_to_excel, export_to_pdf, get_report_filename
from admin_dashboard import render_admin_dashboard
from support_service import (
    submit_ticket, get_user_tickets,
    TICKET_TYPES, STATUS_LABELS, PRIORITY_LABELS,
)


# ══════════════════════════════════════════════════════════════
# PAGE CONFIG
# ══════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="🇮🇳 Trade Intelligence Engine",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Global CSS ────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

[data-testid="metric-container"] {
    background: linear-gradient(135deg,#1a1a2e 0%,#16213e 100%);
    border: 1px solid #0f3460; border-radius: 12px;
    padding: 16px; box-shadow: 0 4px 15px rgba(0,0,0,0.2);
}
[data-testid="metric-container"] label            { color:#a0aec0 !important; font-size:0.78rem !important; }
[data-testid="metric-container"] [data-testid="metric-value"]
                                                   { color:#e2e8f0 !important; font-size:1.55rem !important; font-weight:700 !important; }

.stTabs [data-baseweb="tab-list"]  { gap:3px; flex-wrap:wrap; }
.stTabs [data-baseweb="tab"]       { border-radius:8px 8px 0 0; padding:7px 13px; font-size:0.82rem; font-weight:500; }
.stTabs [aria-selected="true"]     { background:#0f3460 !important; color:white !important; }

.stButton > button                 { border-radius:8px; font-weight:600; transition:all 0.18s; }
.stButton > button:hover           { transform:translateY(-1px); box-shadow:0 4px 14px rgba(0,0,0,0.35); }

.rate-bar-wrap { background:#1a1a2e; border-radius:8px; padding:9px 14px; margin-bottom:6px; }

.admin-badge   { background:linear-gradient(135deg,#f6d365,#fda085);
                 color:#1a1a2e; font-size:0.68rem; font-weight:700;
                 padding:2px 8px; border-radius:20px; margin-left:6px; vertical-align:middle; }

.conf-high { color:#48bb78; font-weight:600; }
.conf-med  { color:#ecc94b; font-weight:600; }
.conf-low  { color:#fc8181; font-weight:600; }

.info-card { background:#1a1a2e; border:1px solid #0f3460; border-radius:12px; padding:16px; margin:8px 0; }

.auth-card { background:#161b22; border:1px solid #30363d; border-radius:14px; padding:28px 32px; }

@media (max-width:768px) {
    .block-container { padding:0.5rem 0.75rem !important; }
    [data-testid="metric-container"] { padding:10px !important; }
    [data-testid="metric-value"]     { font-size:1.2rem !important; }
    .stTabs [data-baseweb="tab"]     { padding:5px 7px; font-size:0.72rem; }
    h1 { font-size:1.35rem !important; }
    h2 { font-size:1.15rem !important; }
}
</style>
""", unsafe_allow_html=True)

DATASET_PATH = os.path.join(os.path.dirname(__file__), "data", "trade_map_2024.xls")


# ══════════════════════════════════════════════════════════════
# SESSION STATE  (initialise once)
# ══════════════════════════════════════════════════════════════

_DEFAULTS = {
    "user":           None,
    "trade_data":     None,
    "db_uploaded":    False,
    "rate_info":      None,
    # 2FA
    "otp_pending":    False,
    "otp_email":      None,
    "otp_user_tmp":   None,
    # Forgot password (OTP-based, 3 steps)
    "pw_reset_step":     0,
    "pw_reset_email":    None,
    "pw_reset_mode":     False,
    "pw_reset_token":    None,
    "pw_reset_done":     False,
    # Report state
    "last_result":    None,
    "last_product":   None,
    "last_mode":      None,
    # TradeGPT chat history
    "chat_history":   [],
    "chat_context":   None,
    # New feature states
    "risk_result":    None,
    "price_result":   None,
    "comp_result":    None,
    "ideas_result":   None,
    "supplier_result":None,
    "doc_result":     None,
    "compliance_result": None,
    "report_result":  None,
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ══════════════════════════════════════════════════════════════
# DATASET LOADER
# ══════════════════════════════════════════════════════════════

@st.cache_data(show_spinner=False)
def _load_data(path: str):
    return load_trade_data(path)

def get_trade_data() -> list:
    if st.session_state.trade_data is None and os.path.exists(DATASET_PATH):
        st.session_state.trade_data = _load_data(DATASET_PATH)
    return st.session_state.trade_data or []




# ══════════════════════════════════════════════════════════════
# URL HANDLING  (email confirmation only — password reset via OTP)
# ══════════════════════════════════════════════════════════════
#
# Password reset NO LONGER uses Supabase email links.
# We use our own OTP flow entirely within Streamlit.
# This section only handles email confirmation after sign-up.

def _handle_url_tokens() -> None:
    """
    Handles email confirmation links from Supabase (type=signup).
    Password reset is handled in-app via OTP — no URL tokens needed.
    """
    params = st.query_params

    # PKCE confirmation code (?code=)
    code = params.get("code", "")
    if code:
        st.query_params.clear()
        with st.spinner("🔐 Confirming your email…"):
            result = exchange_code_for_session(code)
        if result["status"] == "success":
            st.session_state.user = {
                "id":       result["user"]["id"],
                "email":    result["user"]["email"],
                "role":     "free",
                "is_admin": False,
            }
            st.success("✅ Email confirmed — you are now logged in!")
            st.balloons()
            st.rerun()
        else:
            st.error(f"❌ {result['message']}")
        return

    # Legacy implicit token (?access_token= type=signup)
    token  = params.get("access_token", "")
    rtoken = params.get("refresh_token", "")
    kind   = params.get("type", "")

    if not token:
        return

    if kind in ("signup", "magiclink", "") and st.session_state.user is None:
        with st.spinner("🔐 Verifying your email…"):
            result = login_with_token(token, rtoken)
        st.query_params.clear()
        if result["status"] == "success":
            st.session_state.user = result["user"]
            st.success("✅ Email confirmed — you are now logged in!")
            st.balloons()
            st.rerun()
        else:
            st.error(
                f"❌ Confirmation failed: {result['message']}\n\n"
                "The link may have expired. Please log in manually."
            )


_handle_url_tokens()


# ══════════════════════════════════════════════════════════════
# WIDGETS
# ══════════════════════════════════════════════════════════════

def render_rate_limit_bar() -> dict:
    """Render live rate-limit progress bar; return info dict."""
    user = st.session_state.user
    info = check_rate_limit(user["id"], user.get("role", "free"))
    st.session_state.rate_info = info

    pct   = info["used"] / max(info["limit"], 1)
    color = "#48bb78" if pct < 0.6 else "#ecc94b" if pct < 0.85 else "#fc8181"

    st.markdown(f"""
    <div class="rate-bar-wrap">
      <div style="display:flex;justify-content:space-between;margin-bottom:5px;">
        <span style="color:#a0aec0;font-size:0.76rem;">Daily Queries</span>
        <span style="color:{color};font-size:0.76rem;font-weight:600;">
          {info['used']} / {info['limit']} used &mdash; {info['remaining']} remaining
        </span>
      </div>
      <div style="background:#2d3748;border-radius:3px;height:5px;">
        <div style="width:{min(pct*100,100):.0f}%;height:5px;border-radius:3px;
                    background:{color};transition:width 0.4s;"></div>
      </div>
      <div style="color:#718096;font-size:0.68rem;margin-top:3px;">
        Resets: {info['reset_at']}
      </div>
    </div>
    """, unsafe_allow_html=True)
    return info


def render_header() -> None:
    user     = st.session_state.user
    is_admin = user.get("is_admin", False)
    role     = user.get("role", "free")
    badge    = '<span class="admin-badge">ADMIN</span>' if is_admin else ""

    c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
    with c1:
        st.markdown(f"## 🇮🇳 Trade Intelligence Engine {badge}",
                    unsafe_allow_html=True)
    with c2:
        st.metric("User", user["email"].split("@")[0])
    with c3:
        st.metric("Plan", role.upper())
    with c4:
        if st.button("🚪 Logout", use_container_width=True):
            logout_user(user["id"], user["email"])
            for k in _DEFAULTS:
                st.session_state[k] = _DEFAULTS[k]
            st.rerun()

    render_rate_limit_bar()
    st.markdown("---")


def _download_row(result: dict, product: str, mode: str, email: str) -> None:
    """Three download buttons: Excel · PDF · JSON."""
    st.markdown("#### 📥 Download Report")
    dc1, dc2, dc3 = st.columns(3)

    with dc1:
        try:
            buf  = export_to_excel(result, product, mode, email)
            name = get_report_filename(product, mode, "xlsx")
            st.download_button(
                "📊 Excel (.xlsx)", data=buf, file_name=name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        except Exception as e:
            st.error(f"Excel: {e}")

    with dc2:
        try:
            buf  = export_to_pdf(result, product, mode, email)
            name = get_report_filename(product, mode, "pdf")
            st.download_button(
                "📄 PDF (.pdf)", data=buf, file_name=name,
                mime="application/pdf",
                use_container_width=True,
            )
        except Exception as e:
            st.error(f"PDF: {e}")

    with dc3:
        st.download_button(
            "📋 JSON (.json)",
            data=_json.dumps(result, indent=2),
            file_name=get_report_filename(product, mode, "json"),
            mime="application/json",
            use_container_width=True,
        )


# ══════════════════════════════════════════════════════════════
# AUTH PAGES
# ══════════════════════════════════════════════════════════════

def _page_password_reset() -> None:
    """
    3-step OTP-based password reset — runs entirely inside Streamlit.
    No redirect links, no hash fragments, no browser issues.

    Step 0 → idle (not shown, handled in login_page Forgot Password tab)
    Step 1 → OTP sent, waiting for user to enter it
    Step 2 → OTP verified, user enters new password
    """
    step = st.session_state.get("pw_reset_step", 0)

    if step == 0:
        # Nothing to show — handled inside the Forgot Password tab
        return

    _, center, _ = st.columns([1, 2, 1])
    email = st.session_state.get("pw_reset_email", "")

    with center:

        # ── STEP 1: Enter OTP ──────────────────────────────
        if step == 1:
            st.markdown(f"""
            <div class="auth-card" style="text-align:center;margin-top:24px;">
              <div style="font-size:3rem;">📧</div>
              <h2 style="color:#e2e8f0;font-size:1.4rem;margin:10px 0 6px;">
                Check Your Email
              </h2>
              <p style="color:#8b949e;font-size:0.88rem;margin:0;">
                We sent a 6-digit reset code to<br>
                <strong style="color:#63b3ed;">{email}</strong>
              </p>
              <p style="color:#6e7681;font-size:0.78rem;margin:8px 0 0;">
                ⏱ Code expires in 5 minutes · Check spam if not received
              </p>
            </div>
            """, unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)

            with st.form("pr_otp_form"):
                otp_val = st.text_input(
                    "🔢 Enter 6-digit Reset Code",
                    placeholder="e.g. 482931",
                    max_chars=6,
                )
                c1, c2 = st.columns(2)
                with c1:
                    verify_btn = st.form_submit_button(
                        "✅ Verify Code", use_container_width=True, type="primary"
                    )
                with c2:
                    resend_btn = st.form_submit_button(
                        "🔄 Resend Code", use_container_width=True
                    )

            if verify_btn:
                if not otp_val.strip():
                    st.error("Please enter the code.")
                else:
                    with st.spinner("Verifying…"):
                        res = verify_reset_otp(email, otp_val.strip())
                    if res["status"] == "success":
                        st.session_state.pw_reset_step = 2
                        st.rerun()
                    else:
                        st.error(f"❌ {res['message']}")

            if resend_btn:
                with st.spinner("Sending new code…"):
                    res = request_password_reset(email)
                st.success("✅ New code sent — check your inbox.")

            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("← Back to Login", use_container_width=True):
                st.session_state.pw_reset_step  = 0
                st.session_state.pw_reset_email = None
                st.rerun()

        # ── STEP 2: Enter New Password ─────────────────────
        elif step == 2:
            st.markdown("""
            <div class="auth-card" style="text-align:center;margin-top:24px;">
              <div style="font-size:3rem;">🔑</div>
              <h2 style="color:#e2e8f0;font-size:1.4rem;margin:10px 0 6px;">
                Set New Password
              </h2>
              <p style="color:#8b949e;font-size:0.88rem;margin:0;">
                Code verified ✅ · Now choose a new password
              </p>
            </div>
            """, unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)

            with st.form("pr_pw_form"):
                pw1 = st.text_input(
                    "🔑 New Password", type="password", placeholder="Min 6 characters"
                )
                pw2 = st.text_input(
                    "🔑 Confirm Password", type="password", placeholder="Repeat new password"
                )
                save_btn = st.form_submit_button(
                    "✅ Update Password", use_container_width=True, type="primary"
                )

            if save_btn:
                if not pw1 or not pw2:
                    st.error("Please fill in both fields.")
                elif pw1 != pw2:
                    st.error("❌ Passwords do not match.")
                elif len(pw1) < 6:
                    st.error("❌ Password must be at least 6 characters.")
                else:
                    with st.spinner("Updating password…"):
                        res = admin_update_user_password(email, pw1)
                    if res["status"] == "success":
                        st.session_state.pw_reset_step  = 0
                        st.session_state.pw_reset_email = None
                        st.session_state.pw_reset_done  = True
                        st.balloons()
                        st.rerun()
                    else:
                        st.error(f"❌ {res['message']}")

            # ── Show success after rerun ───────────────────
            if st.session_state.get("pw_reset_done"):
                st.markdown("""
                <div style="background:#0d2a1a;border:1px solid #27ae60;border-radius:12px;
                            padding:28px;text-align:center;margin-top:16px;">
                  <div style="font-size:3rem;">✅</div>
                  <h2 style="color:#48bb78;margin:10px 0 6px;">Password Updated!</h2>
                  <p style="color:#a0aec0;font-size:0.9rem;">
                    You can now log in with your new password.
                  </p>
                </div>
                """, unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("← Back to Login", use_container_width=True):
                st.session_state.pw_reset_step  = 0
                st.session_state.pw_reset_email = None
                st.session_state.pw_reset_done  = False
                st.rerun()


def _page_otp_verification() -> None:
    """2FA OTP entry screen — shown after successful password login."""
    _, center, _ = st.columns([1, 2, 1])
    email = st.session_state.otp_email

    with center:
        st.markdown(f"""
        <div class="auth-card" style="text-align:center;">
          <div style="font-size:3rem;">🔐</div>
          <h2 style="color:#e2e8f0;font-size:1.5rem;margin:10px 0 6px;">
            Two-Factor Verification
          </h2>
          <p style="color:#8b949e;font-size:0.9rem;margin:0;">
            A 6-digit code was sent to<br>
            <strong style="color:#63b3ed;">{email}</strong>
          </p>
          <p style="color:#6e7681;font-size:0.8rem;margin:6px 0 0;">Expires in 5 minutes.</p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        with st.form("otp_form"):
            otp_val = st.text_input(
                "Enter 6-digit OTP",
                placeholder="e.g.  4 8 2 9 3 1",
                max_chars=6,
            )
            c1, c2 = st.columns(2)
            with c1:
                verify = st.form_submit_button(
                    "✅ Verify & Login", use_container_width=True, type="primary"
                )
            with c2:
                resend = st.form_submit_button(
                    "🔄 Resend OTP", use_container_width=True
                )

        if verify:
            if not otp_val.strip():
                st.error("Please enter the OTP.")
            else:
                with st.spinner("Verifying…"):
                    res = verify_otp(email, otp_val.strip())
                if res["status"] == "success":
                    st.session_state.user       = st.session_state.otp_user_tmp
                    st.session_state.otp_pending  = False
                    st.session_state.otp_email    = None
                    st.session_state.otp_user_tmp = None
                    st.success("✅ Verified! Logging you in…")
                    st.balloons()
                    st.rerun()
                else:
                    st.error(f"❌ {res['message']}")

        if resend:
            with st.spinner("Sending new OTP…"):
                res = send_otp_email(email, email.split("@")[0])
            if res["status"] == "success":
                st.success("✅ New OTP sent — check your inbox.")
            else:
                st.warning(
                    f"⚠️ Could not send OTP ({res['message']}). "
                    "Check SMTP settings in `.env`."
                )

        st.markdown("---")
        if st.button("← Back to Login", use_container_width=True):
            st.session_state.otp_pending  = False
            st.session_state.otp_email    = None
            st.session_state.otp_user_tmp = None
            st.rerun()


def login_page() -> None:
    """Main auth page — dispatches to sub-pages based on session state."""

    if st.session_state.get("pw_reset_step", 0) > 0 or st.session_state.get("pw_reset_done"):
        _page_password_reset()
        return

    if st.session_state.otp_pending:
        _page_otp_verification()
        return

    # ── Normal login / register page ──────────────
    _, center, _ = st.columns([1, 2, 1])
    with center:
        st.markdown("""
        <div style="text-align:center;padding:2rem 0 1.2rem;">
          <h1 style="font-size:1.9rem;font-weight:700;color:#e2e8f0;">
            🇮🇳 Trade Intelligence Engine
          </h1>
          <p style="color:#8b949e;font-size:0.88rem;margin:4px 0 0;">
            Powered by Llama 3.3 70B &nbsp;·&nbsp; ITC Trade Map 2024
          </p>
        </div>
        """, unsafe_allow_html=True)

        tab_login, tab_reg, tab_forgot = st.tabs([
            "🔐 Login", "📝 Register", "🔑 Forgot Password"
        ])

        # ── LOGIN ──────────────────────────────────
        with tab_login:
            st.markdown("<br>", unsafe_allow_html=True)
            with st.form("login_form"):
                email    = st.text_input("📧 Email",    placeholder="you@example.com")
                password = st.text_input("🔑 Password", type="password",
                                         placeholder="••••••••")
                enable_2fa = st.checkbox(
                    "🔐 Enable Two-Factor Authentication (2FA)",
                    value=False,
                    help="Sends a one-time code to your email for extra security.",
                )
                submit = st.form_submit_button(
                    "Login →", use_container_width=True, type="primary"
                )

            if submit:
                if not email or not password:
                    st.error("Please fill in both fields.")
                else:
                    with st.spinner("Authenticating…"):
                        result = login_user(email, password)

                    if result["status"] == "success":
                        if enable_2fa:
                            with st.spinner("Sending OTP to your email…"):
                                otp_res = send_otp_email(
                                    email, email.split("@")[0]
                                )
                            if otp_res["status"] == "success":
                                st.session_state.otp_pending  = True
                                st.session_state.otp_email    = email
                                st.session_state.otp_user_tmp = result["user"]
                                st.rerun()
                            else:
                                st.warning(
                                    f"⚠️ Could not send OTP ({otp_res['message']}). "
                                    "Logging in without 2FA."
                                )
                                st.session_state.user = result["user"]
                                st.rerun()
                        else:
                            st.session_state.user = result["user"]
                            st.rerun()
                    else:
                        st.error(f"❌ {result['message']}")

        # ── REGISTER ───────────────────────────────
        with tab_reg:
            st.markdown("<br>", unsafe_allow_html=True)
            with st.form("register_form"):
                r_email = st.text_input("📧 Email",            placeholder="you@example.com",       key="reg_email")
                r_pw    = st.text_input("🔑 Password",         type="password",
                                        placeholder="Min 6 characters",           key="reg_pw")
                r_pw2   = st.text_input("🔑 Confirm Password", type="password",
                                        placeholder="Repeat password",            key="reg_pw2")
                r_sub   = st.form_submit_button(
                    "Create Account →", use_container_width=True, type="primary"
                )

            if r_sub:
                if not r_email or not r_pw or not r_pw2:
                    st.error("Please fill in all fields.")
                elif r_pw != r_pw2:
                    st.error("❌ Passwords do not match.")
                elif len(r_pw) < 6:
                    st.error("❌ Password must be at least 6 characters.")
                else:
                    with st.spinner("Creating account…"):
                        result = sign_up_user(r_email, r_pw)

                    if result["status"] == "success":
                        if result.get("email_confirmation_required"):
                            # ── Confirmation page ──────────────────────
                            st.markdown("""
                            <div style="background:#0d2137;border:1px solid #1a6fa8;
                                        border-radius:12px;padding:28px;text-align:center;
                                        margin-top:12px;">
                              <div style="font-size:3rem;">📧</div>
                              <h3 style="color:#63b3ed;margin:10px 0 6px;">Check Your Inbox</h3>
                              <p style="color:#a0aec0;font-size:0.9rem;line-height:1.6;">
                                We sent a confirmation link to<br>
                                <strong style="color:#e2e8f0;">{email}</strong><br><br>
                                Click the link — you will be logged in <strong>automatically</strong>,
                                no password required.
                              </p>
                              <p style="color:#6e7681;font-size:0.78rem;margin-top:14px;">
                                ⏱ Link expires in 24 hours &nbsp;·&nbsp; Check spam if not received
                              </p>
                            </div>
                            """.format(email=r_email), unsafe_allow_html=True)
                            st.balloons()
                        else:
                            st.success("✅ Account created! Please log in.")
                            st.balloons()
                    else:
                        st.error(f"❌ {result['message']}")

        # ── FORGOT PASSWORD ────────────────────────
        with tab_forgot:
            st.markdown("<br>", unsafe_allow_html=True)

            # ── Success banner after completed reset ───────
            if st.session_state.get("pw_reset_done"):
                st.markdown("""
                <div style="background:#0d2a1a;border:1px solid #27ae60;border-radius:12px;
                            padding:24px;text-align:center;">
                  <div style="font-size:2.5rem;">✅</div>
                  <h3 style="color:#48bb78;margin:8px 0 4px;">Password Updated!</h3>
                  <p style="color:#a0aec0;font-size:0.88rem;">
                    Log in with your new password.
                  </p>
                </div>
                """, unsafe_allow_html=True)
                if st.button("← Back to Login", use_container_width=True,
                             type="primary", key="fp_done_btn"):
                    st.session_state.pw_reset_done = False
                    st.rerun()

            else:
                st.markdown("""
                <div style="background:#161b22;border:1px solid #30363d;border-radius:10px;
                            padding:14px 18px;margin-bottom:16px;">
                  <p style="color:#8b949e;margin:0;font-size:0.88rem;">
                    Enter your account email. We will send a
                    <strong style="color:#e2e8f0;">6-digit reset code</strong>
                    to your inbox — no links, no redirects needed.
                  </p>
                </div>
                """, unsafe_allow_html=True)

                # ── SMTP connectivity test ──────────────────
                with st.expander("⚙️ Test Email Configuration (click if code not received)"):
                    st.caption("Tests whether your SMTP settings in .env are working correctly.")
                    if st.button("🔌 Run SMTP Test", key="smtp_test_btn"):
                        with st.spinner("Testing SMTP connection…"):
                            diag = smtp_diagnostic()
                        if diag["status"] == "success":
                            st.success(f"✅ SMTP OK — {diag['message']}")
                        else:
                            st.error(f"❌ SMTP Failed\n\n{diag['message']}")
                            st.code("""
# Add these to your .env file:
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your@gmail.com
SMTP_PASS=your-16-char-app-password   # NOT your Gmail password!
SMTP_FROM=your@gmail.com

# To create a Gmail App Password:
# myaccount.google.com → Security → 2-Step Verification → App Passwords
                            """, language="bash")

                with st.form("forgot_pw_form"):
                    fp_email = st.text_input(
                        "📧 Account Email", placeholder="you@example.com"
                    )
                    fp_sub = st.form_submit_button(
                        "📨 Send Reset Code", use_container_width=True, type="primary"
                    )

                if fp_sub:
                    if not fp_email.strip():
                        st.error("Please enter your email address.")
                    else:
                        with st.spinner("Sending reset code to your email…"):
                            result = request_password_reset(fp_email.strip())

                        if result["status"] == "error":
                            # Show the real error — no more silent failures
                            st.error(f"❌ Could not send reset code:\n\n{result['message']}")
                            if "App Password" in result["message"] or "authentication" in result["message"].lower():
                                st.info(
                                    "**Gmail App Password setup:**\n"
                                    "1. Go to myaccount.google.com\n"
                                    "2. Security → 2-Step Verification (must be ON)\n"
                                    "3. App Passwords → Create → name it 'Trade Engine'\n"
                                    "4. Copy the 16-character password → paste as SMTP_PASS in .env"
                                )
                        else:
                            st.session_state.pw_reset_step  = 1
                            st.session_state.pw_reset_email = fp_email.strip()
                            st.rerun()


# ══════════════════════════════════════════════════════════════
# TRADE ANALYSIS TAB
# ══════════════════════════════════════════════════════════════

def tab_trade_analysis(records: list) -> None:
    user      = st.session_state.user
    rate_info = render_rate_limit_bar()

    if not rate_info["allowed"]:
        st.error(
            f"🚫 Daily limit reached ({rate_info['limit']} queries for **{user.get('role','free').upper()}** plan). "
            f"Resets at **{rate_info['reset_at']}**.\n\n"
            "Contact admin to upgrade your plan."
        )
        return

    col1, col2 = st.columns([3, 1])
    with col1:
        product = st.text_area(
            "📦 Product Description",
            placeholder=(
                "e.g., Organic turmeric powder, 95% curcumin, pharmaceutical grade, "
                "bulk 25 kg HDPE bags, for nutraceutical export…"
            ),
            height=110,
            help="More detail = better accuracy. Include grade, composition, packaging, end-use.",
        )
    with col2:
        mode = st.selectbox(
            "🔍 Analysis Mode",
            ["Import", "Export", "Knowledge"],
            help="Import: duties & restrictions | Export: policy & incentives | Knowledge: GST & compliance",
        )
        st.markdown("<br>", unsafe_allow_html=True)
        run = st.button("🚀 Run Analysis", use_container_width=True, type="primary")

    if not run:
        # Show previous result if available
        if st.session_state.last_result:
            st.markdown("---")
            st.info("📋 Previous result is available for download below.")
            _download_row(
                st.session_state.last_result,
                st.session_state.last_product,
                st.session_state.last_mode,
                user["email"],
            )
        return

    if not product.strip():
        st.warning("⚠️ Please enter a product description.")
        return

    with st.spinner(
        f"🤖 Analysing with Llama 3.3 70B… "
        f"({rate_info['remaining'] - 1} queries remaining today)"
    ):
        result = trade_intelligence_engine(product, mode)

    if "error" in result:
        st.error(f"❌ {result['error']}")
        return

    # ── Persist + log ──────────────────────────────
    st.session_state.last_result  = result
    st.session_state.last_product = product
    st.session_state.last_mode    = mode
    _log_result = log_trade_usage(user_id=user["id"], email=user["email"],
                                  mode=mode, product=product, result=result)
    if _log_result.get("status") == "error":
        st.caption(f"⚠️ Usage logging failed (admin notified): {_log_result['message']}")
    notify_user_limit_warning(user["id"], user["email"],
                              rate_info["used"] + 1, rate_info["limit"])

    # ── Confidence badge ───────────────────────────
    conf = (result.get("data_confidence") or "medium").lower()
    conf_label = {
        "high":   '<span class="conf-high">● High Confidence</span>',
        "medium": '<span class="conf-med">● Medium Confidence</span>',
        "low":    '<span class="conf-low">● Low Confidence — verify manually</span>',
    }.get(conf, '<span class="conf-med">● Medium Confidence</span>')

    st.markdown(f"### ✅ Analysis Complete &nbsp; {conf_label}",
                unsafe_allow_html=True)

    if result.get("validation_warning"):
        st.warning(f"⚠️ {result['validation_warning']}")

    # ── Mode-specific display ──────────────────────
    if mode == "Import":
        st.markdown("#### 📦 Import Analysis")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("HS Code",          result.get("hs_code", "N/A"))
        c2.metric("Basic Duty (BCD)", result.get("basic_customs_duty_percent", "N/A"))
        c3.metric("IGST",             result.get("igst_percent", "N/A"))
        c4.metric("Total Landed Cost",result.get("total_landed_cost_percent", "N/A"))

        status = result.get("import_policy_status", "N/A")
        if   status == "Free":       st.success(f"**Import Status:** {status}  |  SWS: {result.get('social_welfare_surcharge_percent','N/A')}")
        elif status == "Restricted": st.warning(f"**Import Status:** {status}  |  SWS: {result.get('social_welfare_surcharge_percent','N/A')}")
        else:                        st.error(  f"**Import Status:** {status}")

        if result.get("license_required"):    st.warning("⚠️ Import licence required")
        if result.get("scomet_applicable"):   st.warning("⚠️ SCOMET controls applicable")
        if result.get("special_conditions"):  st.info(f"**Special Conditions:** {result['special_conditions']}")

    elif mode == "Export":
        st.markdown("#### 📤 Export Analysis")
        c1, c2, c3 = st.columns(3)
        c1.metric("HS Code",      result.get("hs_code", "N/A"))
        c2.metric("Export Duty",  result.get("export_duty_percent", "0%"))
        c3.metric("RoDTEP Rate",  result.get("rodtep_rate_percent", "N/A"))

        status = result.get("export_policy_status", "N/A")
        if   status == "Free":       st.success(f"**Export Status:** {status}")
        elif status == "Restricted": st.warning(f"**Export Status:** {status}")
        else:                        st.error(  f"**Export Status:** {status}")

        if result.get("rodtep_applicable"):   st.success("✅ RoDTEP applicable")
        if result.get("rosctl_applicable"):   st.success("✅ RoSCTL applicable")
        if result.get("export_incentive_notes"):
            st.info(f"**Incentives:** {result['export_incentive_notes']}")
        if result.get("documentation_required"):
            st.info(f"**Documents Required:** {result['documentation_required']}")
        if result.get("restricted_countries") and result["restricted_countries"] not in ("none", "None", ""):
            st.warning(f"⚠️ **Country Restrictions:** {result['restricted_countries']}")

        # Auto-show top 3 recommended markets
        if records:
            st.markdown("---")
            st.markdown("#### 🌍 Top 3 Recommended Export Markets")
            cols = st.columns(3)
            for i, (r, col) in enumerate(zip(get_top_markets(records, 3), cols)):
                val_str = f"${r['_export_value']/1_000_000:.1f}B"
                with col:
                    st.markdown(f"""
                    <div class="info-card">
                      <div style="font-weight:700;font-size:0.95rem;">
                        {"🥇🥈🥉"[i]} {r['country']}
                      </div>
                      <div style="color:#48bb78;font-size:1.3rem;font-weight:700;">
                        {val_str}
                      </div>
                      <div style="color:#a0aec0;font-size:0.78rem;margin-top:4px;">
                        1yr Growth: {r['growth_1yr_pct']}%
                        &nbsp;·&nbsp; Score: {r['opportunity_score']}
                      </div>
                    </div>
                    """, unsafe_allow_html=True)

    else:  # Knowledge
        st.markdown("#### 📚 GST & Compliance Analysis")
        c1, c2, c3 = st.columns(3)
        c1.metric("HS Code",      result.get("hs_code", "N/A"))
        c2.metric("GST Rate",     result.get("gst_percent", "N/A"))
        c3.metric("GST Category", result.get("gst_category", "N/A"))

        if result.get("itc_available"):
            st.success(f"✅ ITC Available — {result.get('itc_conditions','')}")
        else:
            st.warning(f"⚠️ ITC Not Available — {result.get('itc_conditions','')}")

        r_cols = st.columns(3)
        if result.get("fssai_required"):         r_cols[0].warning("⚠️ FSSAI Required")
        if result.get("bis_required"):           r_cols[1].warning("⚠️ BIS Required")
        if result.get("compliance_requirements"):
            st.info(f"**Compliance:** {result['compliance_requirements']}")
        if result.get("other_regulatory") and result["other_regulatory"] not in ("none","None",""):
            st.info(f"**Other Regulatory:** {result['other_regulatory']}")
        if result.get("risk_flags") and result["risk_flags"] not in (None,"null","none","None",""):
            st.error(f"🚨 **Risk Flags:** {result['risk_flags']}")

    with st.expander("📋 Full JSON Response"):
        st.json(result)

    st.markdown("---")
    _download_row(result, product, mode, user["email"])

    # ── Usage stats ────────────────────────────────
    st.markdown("---")
    st.markdown("#### 📊 Your Usage Stats")
    stats = get_user_stats(user["id"])
    if stats["status"] == "success":
        sc1, sc2, sc3, sc4, sc5 = st.columns(5)
        sc1.metric("Total Queries",    stats["total_queries"])
        sc2.metric("Total Logins",     stats["total_logins"])
        sc3.metric("Import Queries",   stats["by_mode"].get("Import", 0))
        sc4.metric("Export Queries",   stats["by_mode"].get("Export", 0))
        sc5.metric("Knowledge Queries",stats["by_mode"].get("Knowledge", 0))


# ══════════════════════════════════════════════════════════════
# MARKET RECOMMENDATIONS TAB
# ══════════════════════════════════════════════════════════════

def tab_market_recommendations(records: list) -> None:
    st.markdown("## 🌍 Top Export Market Recommendations")
    st.caption("Ranked by Opportunity Score — export value, growth, market size, competitive landscape.")

    if not records:
        st.warning("Dataset not loaded. Check that `data/trade_map_2024.xls` is in your project folder.")
        return

    c1, c2, c3 = st.columns(3)
    with c1: n       = st.slider("Markets to show", 3, 15, 5)
    with c2: min_val = st.selectbox("Min export size", ["Any","$100M+","$1B+","$5B+"])
    with c3: sort_by = st.selectbox("Sort by", ["Opportunity Score","Export Value","1yr Growth"])

    thresholds = {"$100M+": 100_000, "$1B+": 1_000_000, "$5B+": 5_000_000}
    filtered = [r for r in records if r["_export_value"] >= thresholds.get(min_val, 0)]
    top = get_top_markets(filtered, n=n)

    if sort_by == "Export Value":
        top = sorted(top, key=lambda r: r["_export_value"], reverse=True)[:n]
    elif sort_by == "1yr Growth":
        top = sorted(top, key=lambda r: float(r["growth_1yr_pct"] or 0), reverse=True)[:n]

    df = pd.DataFrame([{
        "Country":           r["country"],
        "Export ($B)":       round(r["_export_value"] / 1_000_000, 2),
        "1yr Growth (%)":    float(r["growth_1yr_pct"]) if r["growth_1yr_pct"] else 0,
        "Opportunity Score": r["opportunity_score"],
    } for r in top])

    fig = px.bar(df, x="Country", y="Export ($B)",
                 color="Opportunity Score", color_continuous_scale="Viridis",
                 title="Top Export Markets — India 2024", text="Export ($B)")
    fig.update_traces(texttemplate="%{text:.1f}B", textposition="outside")
    fig.update_layout(height=380, margin=dict(t=46, b=16),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font=dict(color="#c9d1d9"))
    st.plotly_chart(fig, use_container_width=True)

    medals = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟",
              "1️⃣1️⃣","1️⃣2️⃣","1️⃣3️⃣","1️⃣4️⃣","1️⃣5️⃣"]
    for i, r in enumerate(top):
        val = r["_export_value"]
        val_str = f"${val/1_000_000:.1f}B" if val >= 1_000_000 else f"${val/1_000:.0f}M"
        bal = r["_trade_balance"]
        bal_str = f"+${bal/1_000_000:.1f}B" if bal >= 0 else f"-${abs(bal)/1_000_000:.1f}B"

        with st.expander(
            f"{medals[i]} {r['country']}  —  Score: {r['opportunity_score']}",
            expanded=(i < 2),
        ):
            cc1, cc2, cc3, cc4 = st.columns(4)
            cc1.metric("Export Value",       val_str)
            cc2.metric("1yr Growth",         f"{r['growth_1yr_pct']}%" if r['growth_1yr_pct'] else "N/A")
            cc3.metric("India's Mkt Share",  f"{r['india_share_partner_imports_pct']}%")
            cc4.metric("World Import Rank",  f"#{int(r['_world_rank'])}" if r['_world_rank'] else "N/A")
            st.caption(
                f"**Trade Balance:** {bal_str}  ·  "
                f"**5yr CAGR:** {r['growth_5yr_pct']}%  ·  "
                f"**Distance:** {r['avg_distance_km']} km  ·  "
                f"**Supply Concentration:** {r['supply_concentration']}"
            )


# ══════════════════════════════════════════════════════════════
# COUNTRY LOOKUP TAB
# ══════════════════════════════════════════════════════════════

def tab_country_lookup(records: list) -> None:
    st.markdown("## 🔎 Country Trade Lookup")
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
    bal_str = (f"🟢 +${bal/1_000_000:.2f}B" if bal >= 0 else f"🔴 -${abs(bal)/1_000_000:.2f}B")

    st.markdown(f"### 🏳️ {selected}")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Export Value 2024", val_str)
    c2.metric("Trade Balance",     bal_str)
    c3.metric("India's Share",     f"{r['india_share_partner_imports_pct']}%")
    c4.metric("1-Year Growth",     f"{r['growth_1yr_pct']}%" if r['growth_1yr_pct'] else "N/A")
    c5.metric("5-Year CAGR",       f"{r['growth_5yr_pct']}%" if r['growth_5yr_pct'] else "N/A")

    st.markdown("---")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("World Import Rank",    f"#{int(r['_world_rank'])}" if r['_world_rank'] else "N/A")
    c2.metric("World Import Share",   f"{r['share_world_imports_pct']}%")
    c3.metric("Avg Distance (km)",    r["avg_distance_km"] or "N/A")
    c4.metric("Supply Concentration", r["supply_concentration"] or "N/A")

    st.markdown("---")
    col1, col2 = st.columns(2)
    for col, score, title, bar_color in [
        (col1, r["opportunity_score"],  "Opportunity Score",  "#27AE60"),
        (col2, r["future_trend_score"], "Future Trend Score", "#2980B9"),
    ]:
        with col:
            fig = go.Figure(go.Indicator(
                mode="gauge+number", value=score,
                title={"text": title, "font": {"size": 13, "color": "#c9d1d9"}},
                number={"font": {"color": "#e2e8f0"}},
                gauge={
                    "axis": {"range": [0, 100], "tickcolor": "#718096"},
                    "bar":  {"color": bar_color},
                    "bgcolor": "#161b22",
                    "steps": [
                        {"range": [0,  40], "color": "#1a0e0e"},
                        {"range": [40, 70], "color": "#1a1a0e"},
                        {"range": [70, 100], "color": "#0e1a0e"},
                    ],
                },
            ))
            fig.update_layout(
                height=260, margin=dict(t=56, b=16, l=16, r=16),
                paper_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig, use_container_width=True)

    opp, fut = r["opportunity_score"], r["future_trend_score"]
    if   opp >= 70 and fut >= 70: st.success(f"🌟 **{selected}** is both a top current AND future growth market for India.")
    elif opp >= 70:                st.info(   f"📦 Strong current market. Monitor for sustained growth.")
    elif fut >= 70:                st.info(   f"🚀 High future potential — consider strategic market entry now.")
    elif opp < 30 and fut < 30:   st.warning(f"⚠️ Limited current or future trade potential.")
    else:                          st.info(   f"📊 Moderate market with selective opportunities.")


# ══════════════════════════════════════════════════════════════
# DASHBOARD TAB
# ══════════════════════════════════════════════════════════════

def tab_dashboard(records: list) -> None:
    st.markdown("## 📈 India Export Dashboard — 2024")
    if not records:
        st.warning("Dataset not loaded.")
        return

    data    = get_dashboard_data(records)
    total_b = data["total_exports_usd_k"] / 1_000_000

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Exports 2024",   f"${total_b:.1f}B")
    c2.metric("Export Destinations",  data["total_countries"])
    c3.metric("Surplus Markets",      data["surplus_count"])
    c4.metric("Deficit Markets",      data["deficit_count"])
    st.markdown("---")

    col1, col2 = st.columns([3, 2])
    with col1:
        df15 = pd.DataFrame([{
            "Country":        r["country"],
            "Export ($B)":    round(r["_export_value"] / 1_000_000, 2),
            "1yr Growth (%)": float(r["growth_1yr_pct"]) if r["growth_1yr_pct"] else 0,
        } for r in data["top15"]])
        fig = px.bar(df15, x="Export ($B)", y="Country", orientation="h",
                     color="1yr Growth (%)", color_continuous_scale="RdYlGn",
                     title="Top 15 Import Markets for Indian Exports")
        fig.update_layout(height=480, yaxis={"categoryorder": "total ascending"},
                          margin=dict(t=46, b=16),
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                          font=dict(color="#c9d1d9"))
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        rd = {k: v for k, v in data["region_totals"].items() if v > 0}
        fig2 = px.pie(values=list(rd.values()), names=list(rd.keys()),
                      title="Exports by Region",
                      color_discrete_sequence=px.colors.qualitative.Set3)
        fig2.update_traces(textposition="inside", textinfo="percent+label")
        fig2.update_layout(height=480, margin=dict(t=46, b=16),
                           paper_bgcolor="rgba(0,0,0,0)",
                           font=dict(color="#c9d1d9"))
        st.plotly_chart(fig2, use_container_width=True)

    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        df_g = pd.DataFrame([{
            "Country": r["country"],
            "1yr Growth (%)": float(r["growth_1yr_pct"]),
            "Export ($B)": round(r["_export_value"] / 1_000_000, 2),
        } for r in data["growth_leaders"]])
        fig3 = px.bar(df_g, x="1yr Growth (%)", y="Country", orientation="h",
                      color="Export ($B)", color_continuous_scale="Blues",
                      title="Fastest Growing Markets (min $100M)")
        fig3.update_layout(height=380, yaxis={"categoryorder": "total ascending"},
                           paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                           font=dict(color="#c9d1d9"))
        st.plotly_chart(fig3, use_container_width=True)

    with col2:
        df_s = pd.DataFrame([{
            "Country": r["country"],
            "Export ($B)": round(r["_export_value"] / 1_000_000, 2),
            "1yr Growth (%)": float(r["growth_1yr_pct"]) if r["growth_1yr_pct"] else 0,
            "India Mkt Share (%)": float(r["india_share_partner_imports_pct"]) if r["india_share_partner_imports_pct"] else 0,
        } for r in records if r["_export_value"] >= 500_000])
        fig4 = px.scatter(df_s, x="Export ($B)", y="1yr Growth (%)",
                          size="India Mkt Share (%)", hover_name="Country",
                          color="India Mkt Share (%)", color_continuous_scale="Viridis",
                          title="Value vs Growth (bubble = India's market share)")
        fig4.update_layout(height=380,
                           paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                           font=dict(color="#c9d1d9"))
        st.plotly_chart(fig4, use_container_width=True)


# ══════════════════════════════════════════════════════════════
# FUTURE TRENDS TAB
# ══════════════════════════════════════════════════════════════

def tab_future_trends(records: list) -> None:
    st.markdown("## 🔮 Future Export Trends")
    st.caption("Markets scored by 2–3 year growth potential: partner import growth, India's untapped share, 5yr momentum.")
    if not records:
        st.warning("Dataset not loaded.")
        return

    trends = get_future_trends(records, n=15)
    df = pd.DataFrame([{
        "Country":                    r["country"],
        "Future Trend Score":         r["future_trend_score"],
        "Partner Import Growth 5yr%": float(r["partner_import_growth_5yr_pct"]) if r["partner_import_growth_5yr_pct"] else 0,
        "India's Current Share %":    float(r["india_share_partner_imports_pct"]) if r["india_share_partner_imports_pct"] else 0,
        "Current Export $B":          round(r["_export_value"] / 1_000_000, 2),
    } for r in trends])

    fig = px.bar(df, x="Country", y="Future Trend Score",
                 color="Partner Import Growth 5yr%", color_continuous_scale="Plasma",
                 title="Top 15 Markets by Future Export Potential",
                 hover_data=["India's Current Share %", "Current Export $B"])
    fig.update_layout(height=400, margin=dict(t=46, b=16),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font=dict(color="#c9d1d9"))
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("### 🎯 Key Insights")
    col1, col2 = st.columns(2)
    emerging = [r for r in trends if r["_india_share"] < 3 and r["_partner_growth"] > 5][:3]
    momentum = [r for r in trends if float(r["growth_5yr_pct"] or 0) > 10 and r["_export_value"] > 1_000_000][:3]
    with col1:
        st.markdown("**🌱 Emerging Opportunities** *(low India share + fast-growing)*")
        for r in emerging:
            st.info(f"**{r['country']}** — India share: {r['india_share_partner_imports_pct']}% · Market growth: {r['partner_import_growth_5yr_pct']}% p.a.")
    with col2:
        st.markdown("**🚀 Momentum Markets** *(India exports growing fast)*")
        for r in momentum:
            st.success(f"**{r['country']}** — ${r['_export_value']/1_000_000:.1f}B · 5yr CAGR: {r['growth_5yr_pct']}%")

    st.markdown("---")
    st.markdown("### 📋 Full Rankings")
    st.dataframe(df.set_index("Country"), use_container_width=True)
    st.markdown("---")
    st.markdown("### 💡 Strategic Recommendations")
    st.markdown("""
| Strategy | Target Markets | Rationale |
|---|---|---|
| **Double down** | USA, UAE, Netherlands | Large proven markets, steady growth |
| **Accelerate** | Singapore, Saudi Arabia | High 1yr growth + strong demand |
| **Explore now** | Markets with <3% India share | Untapped, fast-growing |
| **Monitor** | China | Large market but India share declining |
| **Diversify** | Africa (Nigeria, Kenya) | Fastest-growing region, low competition |
    """)


# ══════════════════════════════════════════════════════════════
# DATA SYNC TAB
# ══════════════════════════════════════════════════════════════

def tab_data_sync(records: list) -> None:
    from supabase_service import supabase as _sb

    # Hard server-side guard — never trust client-side tab visibility alone
    if not st.session_state.user.get("is_admin", False):
        st.error("🚫 Access denied. This section is for administrators only.")
        return

    st.markdown("## 💾 Dataset Sync to Supabase")
    c1, c2 = st.columns(2)
    c1.metric("Records ready", len(records))
    c2.metric("Status", "✅ Synced" if st.session_state.db_uploaded else "⏳ Not synced")

    if not records:
        st.warning("Dataset not found at `data/trade_map_2024.xls`.")
        return

    if st.button("🚀 Upload Dataset to Supabase",
                 type="primary", use_container_width=True):
        with st.spinner(f"Uploading {len(records)} records via direct PostgreSQL…"):
            res = upload_trade_data_to_supabase(records, _sb)
        if res["status"] == "success":
            st.success(f"✅ {res['rows_uploaded']} records uploaded!")
            st.session_state.db_uploaded = True
            st.balloons()
        else:
            st.error(f"❌ {res['message']}")
            if "DATABASE_URL" in str(res["message"]):
                st.info("Add `DATABASE_URL=postgresql://...` to your `.env`\n"
                        "Find it at: Supabase → Settings → Database → Connection String → URI")
            elif "psycopg2" in str(res["message"]):
                st.code("pip install psycopg2-binary", language="bash")

    st.markdown("---")
    st.markdown("### 📧 Notify All Users of New Dataset")
    st.caption("ℹ️ This sends a system notification to all registered users. Admin-only.")

    ds_name = st.text_input(
        "Dataset label",
        value="Trade Map 2024 (Updated)",
        max_chars=80,
        help="Keep it factual — e.g. 'Trade Map 2024 Q1 Update'. No URLs or contact details.",
    )

    # Sanitise: block URLs, phone numbers, email addresses in the label
    import re as _re
    _url_pat     = _re.compile(r"https?://|www\.|\.com|\.in|\.org|\.net", _re.I)
    _phone_pat   = _re.compile(r"\d[\d\s\-\(\)]{7,}\d")
    _email_pat   = _re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}")
    _label_clean = ds_name.strip()
    _blocked     = (
        _url_pat.search(_label_clean)
        or _phone_pat.search(_label_clean)
        or _email_pat.search(_label_clean)
    )

    if _blocked:
        st.error(
            "❌ Dataset label contains a URL, phone number, or email address — not allowed. "
            "Keep it to a plain dataset name only (e.g. 'Trade Map 2024 Q1')."
        )
    elif st.button("📨 Send Email Alert to All Users", use_container_width=True):
        with st.spinner("Sending emails…"):
            res = notify_all_users_new_dataset(_label_clean)
        if res["status"] == "success":
            st.success(f"✅ Sent to {res['sent']} users ({res['failed']} failed)")
        else:
            st.error(f"❌ {res['message']}")
            st.info("Configure SMTP in .env: `SMTP_HOST · SMTP_PORT · SMTP_USER · SMTP_PASS`")


# ══════════════════════════════════════════════════════════════
# SUPPORT TAB
# ══════════════════════════════════════════════════════════════

def tab_support() -> None:
    """
    Support System — 3 sub-sections:
      1. Contact Support   — general help
      2. Report AI Error   — flag a wrong AI answer
      3. Feature Request   — suggest an improvement
    Also shows the user's own ticket history.
    """
    user   = st.session_state.user
    uid    = user["id"]
    email  = user["email"]

    st.markdown("""
    <div style="background:linear-gradient(135deg,#1a3a5c 0%,#0e2a40 100%);
                border-radius:12px;padding:20px 26px;margin-bottom:18px;">
      <h2 style="color:#ffffff;margin:0;font-size:1.3rem;font-weight:700;">
        🎫  Support Center
      </h2>
      <p style="color:#a8d4f5;margin:5px 0 0;font-size:0.82rem;">
        Contact our team · Report AI errors · Request features
      </p>
    </div>
    """, unsafe_allow_html=True)

    sub_tabs = st.tabs([
        "💬 Contact Support",
        "🐛 Report AI Error",
        "💡 Feature Request",
        "📂 My Tickets",
    ])

    # ── 1. CONTACT SUPPORT ──────────────────────────────
    with sub_tabs[0]:
        st.markdown("#### 💬 Contact Support")
        st.caption("Have a question, account issue, or need help? Reach our team directly.")

        with st.form("support_contact_form", clear_on_submit=True):
            cs_subject = st.text_input(
                "Subject *",
                placeholder="e.g. Cannot access my account / Query limit issue",
                max_chars=200,
            )
            cs_priority = st.selectbox(
                "Priority",
                ["low", "medium", "high"],
                index=1,
                format_func=lambda x: PRIORITY_LABELS[x],
            )
            cs_desc = st.text_area(
                "Describe your issue *",
                placeholder=(
                    "Please be as specific as possible.\n"
                    "Include: what you were doing, what you expected, what happened."
                ),
                height=160,
                max_chars=4000,
            )
            cs_sub = st.form_submit_button(
                "📨 Submit Ticket", use_container_width=True, type="primary"
            )

        if cs_sub:
            if not cs_subject.strip() or not cs_desc.strip():
                st.error("Please fill in both Subject and Description.")
            else:
                with st.spinner("Submitting…"):
                    res = submit_ticket(
                        user_id=uid, email=email,
                        ticket_type="contact_support",
                        subject=cs_subject.strip(),
                        description=cs_desc.strip(),
                        priority=cs_priority,
                    )
                if res["status"] == "success":
                    st.success(
                        f"✅ Ticket **#{res['ticket_id']}** submitted! "
                        "We'll get back to you soon."
                    )
                    st.balloons()
                else:
                    st.error(f"❌ {res['message']}")

    # ── 2. REPORT AI ERROR ──────────────────────────────
    with sub_tabs[1]:
        st.markdown("#### 🐛 Report an AI Error")
        st.caption(
            "Did the Trade Engine return an incorrect HS code, wrong duty rate, "
            "or any other inaccurate information? Help us improve."
        )

        with st.form("support_ai_error_form", clear_on_submit=True):
            ae_subject = st.text_input(
                "What was wrong? (brief) *",
                placeholder="e.g. Wrong HS code returned for turmeric export",
                max_chars=200,
            )
            ae_product = st.text_input(
                "Product you queried",
                placeholder="e.g. Organic turmeric, 95% curcumin",
                max_chars=300,
            )
            ae_mode = st.selectbox(
                "Query mode",
                ["Import", "Export", "Knowledge"],
            )
            ae_ai_output = st.text_area(
                "Paste the AI's response (or the incorrect part) *",
                placeholder="Copy-paste what the AI said that was wrong…",
                height=130,
                max_chars=3000,
            )
            ae_correct = st.text_area(
                "What should the correct answer be?",
                placeholder="Provide the correct information if you know it…",
                height=90,
                max_chars=2000,
            )
            ae_priority = st.selectbox(
                "Severity",
                ["low", "medium", "high"],
                index=1,
                format_func=lambda x: PRIORITY_LABELS[x],
            )
            ae_sub = st.form_submit_button(
                "🐛 Submit Error Report", use_container_width=True, type="primary"
            )

        if ae_sub:
            if not ae_subject.strip() or not ae_ai_output.strip():
                st.error("Please fill in the Subject and AI response fields.")
            else:
                full_desc = (
                    f"**Product queried:** {ae_product or 'Not specified'}\n"
                    f"**Mode:** {ae_mode}\n\n"
                    f"**AI output (incorrect):**\n{ae_ai_output.strip()}\n\n"
                    f"**Correct answer:**\n{ae_correct.strip() or 'Not provided'}"
                )
                with st.spinner("Submitting error report…"):
                    res = submit_ticket(
                        user_id=uid, email=email,
                        ticket_type="report_ai_error",
                        subject=ae_subject.strip(),
                        description=full_desc,
                        priority=ae_priority,
                        extra_data={
                            "product": ae_product,
                            "mode":    ae_mode,
                            "ai_output":      ae_ai_output[:2000],
                            "correct_answer": ae_correct[:1000],
                        },
                    )
                if res["status"] == "success":
                    st.success(
                        f"✅ Error report **#{res['ticket_id']}** submitted! "
                        "Thank you — this directly improves the AI."
                    )
                    st.balloons()
                else:
                    st.error(f"❌ {res['message']}")

    # ── 3. FEATURE REQUEST ──────────────────────────────
    with sub_tabs[2]:
        st.markdown("#### 💡 Feature Request")
        st.caption("Have an idea that would make the Trade Engine more useful? We want to hear it.")

        with st.form("support_feature_form", clear_on_submit=True):
            fr_subject = st.text_input(
                "Feature title *",
                placeholder="e.g. Add MEIS/RoDTEP rate calculator for export schemes",
                max_chars=200,
            )
            fr_category = st.selectbox(
                "Category",
                [
                    "Trade Analysis Improvement",
                    "New Data / Dataset",
                    "UI / UX Improvement",
                    "Export / Reports",
                    "Integration (API, Excel, etc.)",
                    "Admin / User Management",
                    "Other",
                ],
            )
            fr_desc = st.text_area(
                "Describe the feature *",
                placeholder=(
                    "What problem does this solve?\n"
                    "Who would benefit from it?\n"
                    "How do you imagine it working?"
                ),
                height=160,
                max_chars=4000,
            )
            fr_priority = st.selectbox(
                "How important is this to you?",
                ["low", "medium", "high"],
                index=1,
                format_func=lambda x: {"low": "Nice to have", "medium": "Important", "high": "Critical for my work"}[x],
            )
            fr_sub = st.form_submit_button(
                "💡 Submit Feature Request", use_container_width=True, type="primary"
            )

        if fr_sub:
            if not fr_subject.strip() or not fr_desc.strip():
                st.error("Please fill in both the Feature title and Description.")
            else:
                full_desc = f"**Category:** {fr_category}\n\n{fr_desc.strip()}"
                with st.spinner("Submitting feature request…"):
                    res = submit_ticket(
                        user_id=uid, email=email,
                        ticket_type="feature_request",
                        subject=fr_subject.strip(),
                        description=full_desc,
                        priority=fr_priority,
                        extra_data={"category": fr_category},
                    )
                if res["status"] == "success":
                    st.success(
                        f"✅ Feature request **#{res['ticket_id']}** submitted! "
                        "We review all requests and prioritise by votes and impact."
                    )
                    st.balloons()
                else:
                    st.error(f"❌ {res['message']}")

    # ── 4. MY TICKETS ───────────────────────────────────
    with sub_tabs[3]:
        st.markdown("#### 📂 My Support Tickets")

        tickets, _t_err = get_user_tickets(uid)
        if _t_err:
            st.error(
                f"❌ Could not load your tickets: {_t_err}\n\n"
                "The support table may not be set up yet. Please contact the admin."
            )
        elif not tickets:
            st.markdown("""
            <div style="background:#161b22;border:1px solid #30363d;border-radius:12px;
                        padding:32px;text-align:center;margin-top:12px;">
              <div style="font-size:2.5rem;">📭</div>
              <p style="color:#8b949e;margin:12px 0 0;font-size:0.9rem;">
                You have not submitted any support tickets yet.
              </p>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.caption(f"Showing {len(tickets)} ticket(s) — newest first.")
            for tkt in tickets:
                _tid    = tkt.get("id")
                _status = tkt.get("status", "open")
                _type   = TICKET_TYPES.get(tkt.get("ticket_type",""), "Support")
                _subj   = tkt.get("subject","")
                _ts     = (tkt.get("created_at") or "")[:10]
                _note   = tkt.get("admin_note", "") or ""
                _s_lbl  = STATUS_LABELS.get(_status, _status)
                _p_lbl  = PRIORITY_LABELS.get(tkt.get("priority","medium"), "")

                with st.expander(
                    f"{_s_lbl} · {_type} — **{_subj[:55]}** ({_ts})"
                ):
                    st.markdown(f"**Ticket ID:** #{_tid}")
                    st.markdown(f"**Status:** {_s_lbl}  ·  **Priority:** {_p_lbl}")
                    st.markdown(f"**Submitted:** {_ts}")
                    if _note:
                        st.markdown(
                            f"<div style='background:#1a2a1a;border:1px solid #27ae60;"
                            f"border-radius:8px;padding:12px;margin-top:10px;"
                            f"font-size:0.85rem;color:#48bb78;'>"
                            f"📝 <strong>Admin response:</strong><br>{_note}</div>",
                            unsafe_allow_html=True,
                        )
                    else:
                        st.caption("⏳ Awaiting admin response.")


# ══════════════════════════════════════════════════════════════
# ADMIN TAB  (delegates to admin_dashboard.py)
# ══════════════════════════════════════════════════════════════

def tab_admin() -> None:
    render_admin_dashboard()


# ══════════════════════════════════════════════════════════════
# HS CODE ENGINE TAB
# ══════════════════════════════════════════════════════════════

def tab_hs_engine() -> None:
    user      = st.session_state.user
    rate_info = render_rate_limit_bar()
    st.markdown("## 🔢 AI HS Code Engine")
    st.caption("Classify any product to its 8-digit ITC-HS 2022 code with duty breakdown.")

    if not rate_info["allowed"]:
        st.error("🚫 Daily limit reached. Upgrade your plan to continue.")
        return

    sub = st.tabs(["🤖 AI Classify", "🔍 Direct Lookup"])

    with sub[0]:
        col1, col2 = st.columns([3, 1])
        with col1:
            product = st.text_area(
                "📦 Product Description",
                placeholder="e.g. Organic turmeric powder, 95% curcumin, pharmaceutical grade, 25kg HDPE bags",
                height=100,
                key="hs_product_input",
            )
        with col2:
            st.markdown("<br>", unsafe_allow_html=True)
            run_hs = st.button("🔢 Classify", use_container_width=True, type="primary", key="hs_classify_btn")

        if run_hs and product.strip():
            with st.spinner("🤖 Classifying with Llama 3.3 70B + dataset lookup…"):
                result = classify_and_enrich(product.strip())
                log_trade_usage(user_id=user["id"], email=user["email"],
                                mode="HS-Classify", product=product.strip(), result=result)

            if "error" in result:
                st.error(f"❌ {result['error']}")
                return

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("HS Code (8-digit)", result.get("hs_code", "N/A"))
            c2.metric("BCD",   result.get("bcd", result.get("basic_customs_duty_percent", "—")))
            c3.metric("IGST",  result.get("igst", result.get("igst_percent", "—")))
            c4.metric("Total Import Burden", result.get("total_import_burden_pct", "—"))

            st.markdown(f"**Chapter:** {result.get('chapter_no','')} — {result.get('chapter_name', result.get('chapter',''))}")
            st.markdown(f"**Description:** {result.get('hs_description', result.get('description',''))}")

            conf = result.get("confidence", 0)
            if conf:
                st.progress(float(conf), text=f"Classification confidence: {float(conf)*100:.0f}%")

            if result.get("classification_rationale"):
                st.info(f"**Rationale:** {result['classification_rationale']}")
            if result.get("validation_warning"):
                st.warning(f"⚠️ {result['validation_warning']}")
            if result.get("scomet_restricted"):
                st.error("🚨 SCOMET CONTROLLED — This product may require special licence. Contact DGFT.")
            if result.get("alternate_codes"):
                st.caption(f"Alternate codes to verify: {', '.join(result['alternate_codes'])}")

            gst  = result.get("gst", result.get("gst_percent", ""))
            rdte = result.get("rodtep_rate", "")
            if gst or rdte:
                cols = st.columns(2)
                if gst:  cols[0].metric("GST Rate",     gst)
                if rdte: cols[1].metric("RoDTEP Rate",  rdte)

            st.markdown(f"🔗 [Verify at ICEGATE]({result.get('verify_url','https://icegate.gov.in')})")

            with st.expander("📋 Full Classification Data"):
                st.json(result)

            _download_row(result, product, "HS-Classify", user["email"])

    with sub[1]:
        hs_input = st.text_input("Enter HS Code (6 or 8 digits)", placeholder="09103010", key="hs_direct_input")
        if st.button("🔍 Lookup", key="hs_direct_btn") and hs_input.strip():
            with st.spinner("Looking up in dataset…"):
                r = classify_and_enrich.__globals__["lookup_hs_code"](hs_input.strip()) \
                    if hasattr(classify_and_enrich, "__globals__") else {}
                from hs_engine import lookup_hs_code
                r = lookup_hs_code(hs_input.strip())

            c1, c2, c3 = st.columns(3)
            c1.metric("BCD",  r.get("bcd", "—"))
            c2.metric("IGST", r.get("igst", "—"))
            c3.metric("GST",  r.get("gst_percent", r.get("rate", "—")))
            if r.get("description"):
                st.info(r["description"])
            if r.get("scomet_restricted"):
                st.error("🚨 SCOMET CONTROLLED")
            st.markdown(f"🔗 [Verify at ICEGATE]({r.get('verify_url','https://icegate.gov.in')})")
            with st.expander("Full dataset record"):
                st.json(r)


# ══════════════════════════════════════════════════════════════
# RISK ANALYZER TAB
# ══════════════════════════════════════════════════════════════

def tab_risk_analyzer() -> None:
    user      = st.session_state.user
    rate_info = render_rate_limit_bar()
    st.markdown("## ⚠️ Trade Risk Analyzer")
    st.caption("Score your trade risk across 6 dimensions — political, currency, tariff, logistics, compliance, payment.")

    if not rate_info["allowed"]:
        st.error("🚫 Daily limit reached.")
        return

    c1, c2, c3 = st.columns(3)
    with c1:
        product   = st.text_input("📦 Product", placeholder="Basmati rice, premium grade", key="risk_product")
    with c2:
        country   = st.text_input("🌍 Target Country", placeholder="United Arab Emirates", key="risk_country")
    with c3:
        direction = st.selectbox("Direction", ["Export", "Import"], key="risk_dir")

    val_usd = st.text_input("Shipment Value (USD)", value="50,000", key="risk_val")

    if st.button("⚠️ Analyze Risk", type="primary", use_container_width=True, key="risk_btn"):
        if not product.strip() or not country.strip():
            st.warning("Enter product and country.")
            return
        with st.spinner("🔍 Analyzing risk profile…"):
            result = analyze_trade_risk(product.strip(), country.strip(), direction, val_usd)
            st.session_state.risk_result = result
            log_trade_usage(user_id=user["id"], email=user["email"],
                            mode="Risk", product=product.strip(), result=result)

    result = st.session_state.risk_result
    if not result or "error" in result:
        if result and "error" in result:
            st.error(f"❌ {result['error']}")
        return

    score = result.get("overall_risk_score", 5)
    label = result.get("overall_risk_label", "Medium")
    color_map = {"green": "#48bb78", "orange": "#ecc94b", "red": "#fc8181"}
    color = color_map.get(result.get("risk_color", "orange"), "#ecc94b")

    st.markdown(f"""
    <div style="background:#1a1a2e;border:2px solid {color};border-radius:12px;
                padding:20px;text-align:center;margin:12px 0;">
      <div style="color:{color};font-size:2.5rem;font-weight:700;">{label} Risk</div>
      <div style="color:#a0aec0;font-size:1rem;">Overall Score: {score}/10</div>
    </div>""", unsafe_allow_html=True)

    dims = result.get("risk_dimensions", {})
    dim_labels = {
        "political_risk": "🏛️ Political",
        "currency_risk":  "💱 Currency",
        "tariff_risk":    "📊 Tariff",
        "logistics_risk": "🚢 Logistics",
        "compliance_risk":"📋 Compliance",
        "payment_risk":   "💰 Payment",
    }
    cols = st.columns(3)
    for i, (key, lbl) in enumerate(dim_labels.items()):
        d = dims.get(key, {})
        s = d.get("score", 5)
        rc = "#48bb78" if s<=3 else ("#fc8181" if s>6 else "#ecc94b")
        with cols[i % 3]:
            st.markdown(f"""
            <div class="info-card" style="text-align:center;">
              <div style="font-size:0.8rem;color:#a0aec0;">{lbl}</div>
              <div style="font-size:1.6rem;font-weight:700;color:{rc};">{s}/10</div>
              <div style="font-size:0.75rem;color:#718096;">{d.get('reason','')}</div>
            </div>""", unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**🔴 Key Risks**")
        for r in result.get("key_risks", []):
            st.markdown(f"- {r}")
    with col2:
        st.markdown("**✅ Mitigation Strategies**")
        for m in result.get("risk_mitigation", []):
            st.markdown(f"- {m}")

    c1, c2, c3 = st.columns(3)
    c1.info(f"**Incoterm:** {result.get('recommended_incoterm','CIF')}")
    c2.info(f"**Payment:** {result.get('payment_recommendation','LC at sight')}")
    c3.info(f"**ECGC:** {'✅ Available' if result.get('ecgc_cover_available') else '—'}")

    if result.get("fta_applicable"):
        st.success(f"🤝 FTA Benefit: {result.get('fta_detail','')}")
    else:
        st.caption(f"ℹ️ {result.get('fta_detail','MFN rates apply')}")

    _download_row(result, product, "Risk-Analysis", user["email"])


# ══════════════════════════════════════════════════════════════
# PRICE INTELLIGENCE TAB
# ══════════════════════════════════════════════════════════════

def tab_price_intelligence() -> None:
    user      = st.session_state.user
    rate_info = render_rate_limit_bar()
    st.markdown("## 💰 Global Price Intelligence")
    st.caption("Benchmark your product's price against global markets — find your margin opportunity.")

    if not rate_info["allowed"]:
        st.error("🚫 Daily limit reached.")
        return

    c1, c2, c3 = st.columns(3)
    with c1: product = st.text_input("📦 Product", placeholder="Turmeric powder", key="price_prod")
    with c2: qty     = st.text_input("Quantity Basis", value="1 MT", key="price_qty")
    with c3: market  = st.text_input("Target Market", value="Global", key="price_mkt")

    if st.button("💰 Get Price Intel", type="primary", use_container_width=True, key="price_btn"):
        if not product.strip():
            st.warning("Enter a product.")
            return
        with st.spinner("📊 Analyzing global prices…"):
            result = get_price_intelligence(product.strip(), qty, market)
            st.session_state.price_result = result
            log_trade_usage(user_id=user["id"], email=user["email"],
                            mode="Price-Intel", product=product.strip(), result=result)

    result = st.session_state.price_result
    if not result or "error" in result:
        if result and "error" in result: st.error(f"❌ {result['error']}")
        return

    fob = result.get("india_fob_price_usd", {})
    dom = result.get("india_domestic_price_inr", {})
    lnd = result.get("target_market_landed_usd", {})
    mgn = result.get("gross_margin_pct", {})

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("India FOB (typical)", f"${fob.get('typical',0)} {fob.get('unit','')}")
    c2.metric("Domestic Price",      f"₹{dom.get('typical',0)} {dom.get('unit','')}")
    c3.metric("Market Landed Price", f"${lnd.get('typical',0)} {lnd.get('unit','')}")
    c4.metric("Gross Margin",        f"{mgn.get('min',0)}–{mgn.get('max',0)}%")

    trend_color = {"Rising":"#48bb78","Falling":"#fc8181","Stable":"#ecc94b"}.get(
        result.get("global_price_trend","Stable"), "#a0aec0")
    st.markdown(f"""
    <div class="info-card">
      <span style="color:{trend_color};font-weight:700;">
        {result.get('global_price_trend','—')} Trend
      </span> — {result.get('trend_reason','')}
    </div>""", unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**🌍 Competing Origins**")
        for c in result.get("competing_origins", []):
            st.markdown(f"- {c}")
    with c2:
        frt = result.get("freight_estimate_usd", {})
        st.markdown("**🚢 Freight Estimates (USD/MT)**")
        if frt:
            st.markdown(f"- To USA: ${frt.get('to_usa',0)}")
            st.markdown(f"- To UAE: ${frt.get('to_uae',0)}")
            st.markdown(f"- To Germany: ${frt.get('to_germany',0)}")

    st.info(f"📌 **India's Position:** {result.get('india_price_advantage','')}")
    if result.get("seasonal_pricing"):
        st.caption(f"📅 Seasonal: {result['seasonal_pricing']}")

    st.warning(f"⚠️ {result.get('data_note','Indicative ranges — verify with market quotes')}")
    _download_row(result, product, "Price-Intel", user["email"])


# ══════════════════════════════════════════════════════════════
# DOCUMENT ANALYZER TAB
# ══════════════════════════════════════════════════════════════

def tab_document_analyzer() -> None:
    user      = st.session_state.user
    rate_info = render_rate_limit_bar()
    st.markdown("## 📄 AI Document Analyzer")
    st.caption("Paste any trade document — Invoice, Packing List, Bill of Lading, BoE, Shipping Bill, LC — to extract and validate all data.")

    if not rate_info["allowed"]:
        st.error("🚫 Daily limit reached.")
        return

    c1, c2 = st.columns([3, 1])
    with c1:
        doc_text = st.text_area(
            "📋 Paste document text here",
            height=200,
            placeholder="Paste your Commercial Invoice, Packing List, Bill of Lading, Bill of Entry, "
                        "Shipping Bill, or Letter of Credit text here...",
            key="doc_text_input",
        )
    with c2:
        doc_type = st.selectbox(
            "Document Type",
            ["auto", "Commercial Invoice", "Packing List", "Bill of Lading",
             "Bill of Entry", "Shipping Bill", "Certificate of Origin", "Letter of Credit"],
            key="doc_type_sel",
        )
        st.markdown("<br>", unsafe_allow_html=True)
        run_doc = st.button("📄 Analyze", type="primary", use_container_width=True, key="doc_btn")

    if run_doc:
        if not doc_text.strip():
            st.warning("Please paste a document.")
            return
        with st.spinner("🤖 Extracting and validating document data…"):
            result = analyze_trade_document(doc_text.strip(), doc_type)
            st.session_state.doc_result = result
            log_trade_usage(user_id=user["id"], email=user["email"],
                            mode="Doc-Analyze", product=f"Document: {doc_type}", result=result)

    result = st.session_state.doc_result
    if not result or "error" in result:
        if result and "error" in result: st.error(f"❌ {result['error']}")
        return

    status = result.get("compliance_status", "OK")
    if status == "OK":
        st.success(f"✅ Document: {result.get('document_type','')}  ·  Status: {status}")
    elif status == "Review Needed":
        st.warning(f"⚠️ Document: {result.get('document_type','')}  ·  {status}")
    else:
        st.error(f"❌ Document: {result.get('document_type','')}  ·  {status}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Doc Number", result.get("document_number","—") or "—")
    c2.metric("Doc Date",   result.get("document_date","—")   or "—")
    c3.metric("Incoterm",   result.get("incoterm","—")         or "—")
    c4.metric("Total Value",f"{result.get('total_invoice_value',{}).get('currency','USD')} "
              f"{result.get('total_invoice_value',{}).get('amount',0):,.0f}")

    exp = result.get("exporter", {})
    imp = result.get("importer", {})
    if exp.get("name") or imp.get("name"):
        c1, c2 = st.columns(2)
        if exp.get("name"):
            c1.markdown(f"**Exporter:** {exp['name']}" + (f"  ·  IEC: {exp['iec_code']}" if exp.get('iec_code') else ""))
        if imp.get("name"):
            c2.markdown(f"**Importer:** {imp['name']}  ·  {imp.get('country','')}")

    products = result.get("products", [])
    if products:
        st.markdown("**Product Lines:**")
        df_data = []
        for p in products:
            df_data.append({
                "Line": p.get("line_no", ""),
                "Description": p.get("description", "")[:60],
                "HS Code": p.get("hs_code", "—"),
                "✓": "✅" if p.get("hs_code_valid") else "⚠️",
                "Qty": f"{p.get('quantity','')} {p.get('unit','')}",
                "Unit Price": f"${p.get('unit_price_usd',0):,.2f}",
                "Total": f"${p.get('total_value_usd',0):,.2f}",
            })
        st.dataframe(pd.DataFrame(df_data), use_container_width=True, hide_index=True)

    flags = result.get("flags", [])
    missing = result.get("missing_critical_fields", [])
    if flags:
        st.warning("**⚠️ Flags found:**\n" + "\n".join(f"- {f}" for f in flags))
    if missing:
        st.error("**❌ Missing critical fields:**\n" + "\n".join(f"- {m}" for m in missing))
    if result.get("compliance_notes"):
        st.info(f"**Notes:** {result['compliance_notes']}")

    _download_row(result, doc_type, "Doc-Analyze", user["email"])


# ══════════════════════════════════════════════════════════════
# COMPLIANCE CHECKER TAB
# ══════════════════════════════════════════════════════════════

def tab_compliance_checker() -> None:
    user      = st.session_state.user
    rate_info = render_rate_limit_bar()
    st.markdown("## 📋 Trade Compliance Checker")
    st.caption("Check SCOMET controls, DGFT policy, licences, documentation requirements — before you ship.")

    if not rate_info["allowed"]:
        st.error("🚫 Daily limit reached.")
        return

    c1, c2 = st.columns(2)
    with c1:
        product     = st.text_input("📦 Product", placeholder="Sodium cyanide 98% industrial grade", key="comp_prod")
        hs_code     = st.text_input("HS Code (optional)", placeholder="28371100", key="comp_hs")
    with c2:
        origin      = st.text_input("Origin Country", value="India", key="comp_orig")
        destination = st.text_input("Destination Country", placeholder="Germany", key="comp_dest")
    direction = st.selectbox("Direction", ["Export", "Import"], key="comp_dir")

    if st.button("📋 Check Compliance", type="primary", use_container_width=True, key="comp_btn"):
        if not product.strip() or not destination.strip():
            st.warning("Enter product and destination country.")
            return
        with st.spinner("🔍 Running compliance checks…"):
            result = check_trade_compliance(product.strip(), hs_code.strip(),
                                             origin.strip(), destination.strip(), direction)
            st.session_state.compliance_result = result
            log_trade_usage(user_id=user["id"], email=user["email"],
                            mode="Compliance", product=product.strip(), result=result)

    result = st.session_state.compliance_result
    if not result or "error" in result:
        if result and "error" in result: st.error(f"❌ {result['error']}")
        return

    overall = result.get("overall_compliance_status", "CLEAR")
    if overall == "CLEAR":
        st.success(f"✅ **{overall}** — {result.get('compliance_summary','')}")
    elif overall == "CONDITIONAL":
        st.warning(f"⚠️ **{overall}** — {result.get('compliance_summary','')}")
    else:
        st.error(f"🚫 **{overall}** — {result.get('compliance_summary','')}")
        if result.get("blocked_reason"):
            st.error(f"**Reason:** {result['blocked_reason']}")

    checks = result.get("checks", {})
    check_labels = {
        "scomet_control":    "🔬 SCOMET",
        "dgft_policy":       "📜 DGFT Policy",
        "un_sanctions":      "🌐 UN Sanctions",
        "prohibited_items":  "🚫 Prohibited Items",
        "licence_required":  "📄 Licence",
        "quality_standards": "✅ Quality Standards",
    }
    cols = st.columns(3)
    for i, (key, lbl) in enumerate(check_labels.items()):
        chk = checks.get(key, {})
        s   = chk.get("status", "—")
        clr = "#48bb78" if s in ("CLEAR","NOT REQUIRED","OK") else ("#fc8181" if s=="BLOCKED" else "#ecc94b")
        with cols[i % 3]:
            st.markdown(f"""
            <div class="info-card">
              <div style="font-weight:700;font-size:0.85rem;">{lbl}</div>
              <div style="color:{clr};font-weight:600;">{s}</div>
              <div style="font-size:0.75rem;color:#718096;">{chk.get('detail','')}</div>
            </div>""", unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**📄 Required Documents**")
        for d in result.get("required_documents", []):
            st.markdown(f"- {d}")
    with col2:
        st.markdown("**🔜 Next Steps**")
        for s in result.get("recommended_next_steps", []):
            st.markdown(f"- {s}")

    if result.get("conditional_requirements"):
        st.warning("**Conditional Requirements:**\n" + "\n".join(f"- {r}" for r in result["conditional_requirements"]))
    if result.get("certifications_needed"):
        st.info(f"**Certifications:** {', '.join(result['certifications_needed'])}")

    auth = result.get("authority_contacts", {})
    if auth:
        st.caption(f"📞 DGFT: {auth.get('dgft','')}  ·  Customs: {auth.get('customs','')}  ·  SCOMET: {auth.get('scomet_queries', auth.get('scomet',''))}")

    _download_row(result, product, "Compliance", user["email"])


# ══════════════════════════════════════════════════════════════
# COMPETITOR INTELLIGENCE TAB
# ══════════════════════════════════════════════════════════════

def tab_competitor_intelligence() -> None:
    user      = st.session_state.user
    rate_info = render_rate_limit_bar()
    st.markdown("## 🥊 AI Competitor Intelligence")
    st.caption("Analyze India's global competition — know your rivals, find your edge.")

    if not rate_info["allowed"]:
        st.error("🚫 Daily limit reached.")
        return

    c1, c2 = st.columns(2)
    with c1: product = st.text_input("📦 Product", placeholder="Basmati rice", key="comp_i_prod")
    with c2: market  = st.text_input("🌍 Target Market", placeholder="United States", key="comp_i_mkt")

    if st.button("🥊 Analyze Competition", type="primary", use_container_width=True, key="comp_i_btn"):
        if not product.strip() or not market.strip():
            st.warning("Enter product and target market.")
            return
        with st.spinner("📊 Analyzing competitive landscape…"):
            result = get_competitor_intelligence(product.strip(), market.strip())
            st.session_state.comp_result = result
            log_trade_usage(user_id=user["id"], email=user["email"],
                            mode="Competitor-Intel", product=product.strip(), result=result)

    result = st.session_state.comp_result
    if not result or "error" in result:
        if result and "error" in result: st.error(f"❌ {result['error']}")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("India's Market Share",    f"{result.get('india_market_share_pct', result.get('india_current_market_share_pct',0))}%")
    c2.metric("India's Rank",            f"#{result.get('india_rank', result.get('india_rank_in_market',0))}")
    c3.metric("Market Size",             f"${result.get('market_total_imports_usd_m',0)}M")
    c4.metric("Entry Difficulty",        result.get("market_entry_difficulty","Medium"))

    competitors = result.get("top_competitors", [])
    if competitors:
        st.markdown("#### 🏆 Top Competitors")
        df = pd.DataFrame([{
            "Country":       c.get("country",""),
            "Rank":          c.get("rank",""),
            "Market Share":  f"{c.get('share_pct', c.get('market_share_pct',0))}%",
            "Price Level":   c.get("price_level",""),
            "India vs This": c.get("india_vs_this_competitor", c.get("india_vs_competitor",""))[:80],
        } for c in competitors])
        st.dataframe(df, use_container_width=True, hide_index=True)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**✅ India's Strengths**")
        for s in result.get("india_strengths", []):
            st.markdown(f"- {s}")
    with c2:
        st.markdown("**⚠️ India's Weaknesses**")
        for w in result.get("india_weaknesses", []):
            st.markdown(f"- {w}")

    st.info(f"**🎯 Win Strategy:** {result.get('differentiation_strategy','')}")
    if result.get("fta_advantage"):
        st.success(f"🤝 FTA: {result['fta_advantage']}")
    st.caption(f"💰 {result.get('price_competitiveness','')}")

    _download_row(result, product, "Competitor-Intel", user["email"])


# ══════════════════════════════════════════════════════════════
# SMART TRADE IDEAS TAB
# ══════════════════════════════════════════════════════════════

def tab_smart_trade_ideas() -> None:
    user      = st.session_state.user
    rate_info = render_rate_limit_bar()
    st.markdown("## 💡 Smart Trade Ideas")
    st.caption("Tell us about yourself — get 5 tailored, AI-generated import/export business opportunities.")

    if not rate_info["allowed"]:
        st.error("🚫 Daily limit reached.")
        return

    c1, c2, c3 = st.columns(3)
    with c1: budget    = st.selectbox("Budget", ["Under 5 lakhs","5-10 lakhs","10-50 lakhs","50L-1 Cr","1 Cr+"], index=2, key="idea_budget")
    with c2: direction = st.selectbox("Direction", ["Export","Import","Both"], key="idea_dir")
    with c3: industry  = st.selectbox("Industry Focus", ["Any","Agriculture/Food","Textiles","Chemicals","Engineering","Handicrafts","Pharma","Technology","Services"], key="idea_ind")

    profile = st.text_area(
        "Tell us about yourself (optional but improves results)",
        placeholder="e.g. I'm in Gujarat, have a small textile manufacturing unit, know some buyers in UAE, "
                    "looking for export opportunities in textile or agro products...",
        height=90, key="idea_profile",
    )

    if st.button("💡 Generate Trade Ideas", type="primary", use_container_width=True, key="ideas_btn"):
        with st.spinner("🤖 Generating tailored trade opportunities…"):
            result = generate_smart_trade_ideas(
                user_profile=profile.strip() or "Indian entrepreneur/student, open to opportunities",
                budget_inr=budget, direction=direction, industry_focus=industry,
            )
            st.session_state.ideas_result = result
            log_trade_usage(user_id=user["id"], email=user["email"],
                            mode="Trade-Ideas", product="Smart Ideas", result=result)

    result = st.session_state.ideas_result
    if not result or "error" in result:
        if result and "error" in result: st.error(f"❌ {result['error']}")
        return

    if result.get("profile_analysis"):
        st.info(f"**AI Assessment:** {result['profile_analysis']}")

    for idea in result.get("ideas", []):
        rank   = idea.get("rank", "")
        title  = idea.get("title", "")
        diff   = idea.get("difficulty_level","")
        margin = idea.get("typical_margin_pct","")
        invest = idea.get("initial_investment_inr","")

        with st.expander(f"#{rank} — {title}  |  Margin: {margin}  |  {diff}", expanded=(rank == result.get("most_recommended",1))):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Product",    idea.get("product","")[:30])
            c2.metric("HS Range",   idea.get("hs_code_range",""))
            c3.metric("Investment", f"₹{invest}")
            c4.metric("Revenue/mo", f"₹{idea.get('monthly_revenue_potential_inr','')}")

            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f"**🌍 Target Markets:** {', '.join(idea.get('target_markets',[]))}")
                st.markdown(f"**⏱ Time to 1st Shipment:** {idea.get('months_to_first_shipment','')} months")
                st.markdown(f"**📜 Schemes:** {', '.join(idea.get('relevant_schemes',[]))}")
            with c2:
                st.markdown(f"**🚀 Why Now:** {idea.get('why_now','')}")
                st.markdown(f"**🇮🇳 India Advantage:** {idea.get('india_advantage','')}")

            st.warning(f"**⚠️ Main Challenge:** {idea.get('key_challenge','')}")
            st.success(f"**✅ First Step:** {idea.get('first_step','')}")

    if result.get("quick_wins"):
        st.markdown("#### ⚡ Quick Wins (90 days)")
        for q in result["quick_wins"]:
            st.markdown(f"- {q}")

    if result.get("avoid_these"):
        st.markdown("#### 🚫 Avoid These")
        for a in result["avoid_these"]:
            st.markdown(f"- ⚠️ {a}")

    if result.get("first_week_actions"):
        st.markdown("#### 📅 Your First Week")
        for action in result["first_week_actions"]:
            st.markdown(f"- {action}")

    _download_row(result, "Smart Trade Ideas", "Ideas", user["email"])


# ══════════════════════════════════════════════════════════════
# SUPPLIER CHAIN FINDER TAB
# ══════════════════════════════════════════════════════════════

def tab_supplier_finder() -> None:
    user      = st.session_state.user
    rate_info = render_rate_limit_bar()
    st.markdown("## 🔗 Global Supplier Finder")
    st.caption("Find and evaluate global sourcing options for any product you want to import to India.")

    if not rate_info["allowed"]:
        st.error("🚫 Daily limit reached.")
        return

    c1, c2, c3, c4 = st.columns(4)
    with c1: product  = st.text_input("📦 Product to Import", placeholder="Industrial bearings SKF grade", key="sup_prod")
    with c2: qty      = st.text_input("Quantity Required",    placeholder="5 MT / 1000 units",            key="sup_qty")
    with c3: quality  = st.selectbox("Quality Standard", ["Standard","ISO 9001","CE Mark","FDA","Premium","Budget"], key="sup_qual")
    with c4: origin   = st.text_input("Preferred Origin",     value="Any",                                key="sup_orig")

    if st.button("🔗 Find Suppliers", type="primary", use_container_width=True, key="sup_btn"):
        if not product.strip():
            st.warning("Enter a product.")
            return
        with st.spinner("🌍 Analyzing global supply chain…"):
            result = find_global_suppliers(product.strip(), qty.strip() or "1 MT", quality, origin.strip())
            st.session_state.supplier_result = result
            log_trade_usage(user_id=user["id"], email=user["email"],
                            mode="Supplier-Finder", product=product.strip(), result=result)

    result = st.session_state.supplier_result
    if not result or "error" in result:
        if result and "error" in result: st.error(f"❌ {result['error']}")
        return

    st.info(f"**Global Supply:** {result.get('global_supply_overview','')}")

    c1, c2 = st.columns(2)
    c1.metric("India Total Import", f"${result.get('total_india_import_usd_m',0)}M/year")

    origins = result.get("top_supply_origins", [])
    for i, o in enumerate(origins):
        medal = ["🥇","🥈","🥉","4️⃣","5️⃣"][min(i, 4)]
        with st.expander(f"{medal} {o.get('country','')} — {o.get('fob_price_range_usd','')} | Quality: {o.get('quality_level','')}",
                         expanded=(i == 0)):
            c1, c2, c3 = st.columns(3)
            c1.metric("Min Order",    o.get("min_order_qty",""))
            c2.metric("Lead Time",    f"{o.get('lead_time_weeks','')} weeks")
            c3.metric("Landed Markup",o.get("total_landed_markup_pct", o.get("total_landed_cost_markup_pct","")))

            st.markdown(f"**BCD:** {o.get('bcd_pct', o.get('india_import_duty_bcd_pct',''))}  ·  **IGST:** {o.get('igst_pct', o.get('india_igst_pct',''))}")
            if o.get("fta_with_india"):
                st.success(f"✅ FTA with India — Duty saving: {o.get('fta_saving', o.get('fta_duty_saving',''))}")
            if o.get("concerns"):
                st.warning("⚠️ Watch out: " + ", ".join(o["concerns"]))
            if o.get("b2b_platforms"):
                st.caption(f"🛒 Find on: {', '.join(o['b2b_platforms'])}")

    dom = result.get("india_domestic_alternative", {})
    if dom.get("available"):
        st.markdown("---")
        st.markdown("**🇮🇳 Domestic Alternative**")
        c1, c2 = st.columns(2)
        c1.markdown(f"States: {', '.join(dom.get('producing_states', []))}")
        c2.markdown(f"vs Import: {dom.get('domestic_vs_import', dom.get('domestic_price_vs_import',''))}")
        st.info(f"**Recommendation:** {dom.get('recommendation','')}")

    cost = result.get("total_landed_cost_breakdown", {})
    if cost:
        st.markdown("**💰 Landed Cost Breakdown**")
        cols = st.columns(len(cost))
        for i, (k, v) in enumerate(cost.items()):
            cols[min(i, len(cols)-1)].metric(k.replace("_"," ").title(), str(v))

    if result.get("payment_advice"):
        st.info(f"💳 **Payment Advice:** {result['payment_advice']}")

    _download_row(result, product, "Supplier-Finder", user["email"])


# ══════════════════════════════════════════════════════════════
# SHIPMENT COST CALCULATOR TAB
# ══════════════════════════════════════════════════════════════

def tab_shipment_calculator() -> None:
    user      = st.session_state.user
    rate_info = render_rate_limit_bar()
    st.markdown("## 🚢 Shipment Cost Calculator")
    st.caption("Estimate complete export/import costs — freight, duties, port charges, and landed cost.")

    if not rate_info["allowed"]:
        st.error("🚫 Daily limit reached.")
        return

    c1, c2, c3 = st.columns(3)
    with c1:
        product = st.text_input("📦 Product", placeholder="Basmati rice", key="ship_prod")
        hs_code = st.text_input("HS Code (optional)", placeholder="10063020", key="ship_hs")
    with c2:
        origin_port = st.selectbox("Origin Port", [
            "JNPT (Mumbai)", "Mundra (Gujarat)", "Chennai", "Nhava Sheva",
            "Kolkata", "Vizag", "Cochin", "Delhi ICD", "Other"
        ], key="ship_origin")
        destination_port = st.text_input("Destination Port", placeholder="Port of Rotterdam / Dubai Jebel Ali", key="ship_dest")
    with c3:
        weight    = st.number_input("Weight (kg)",  min_value=1.0, value=1000.0, step=100.0, key="ship_wt")
        volume    = st.number_input("Volume (CBM)", min_value=0.1, value=5.0,    step=0.5,   key="ship_vol")
        cargo_val = st.number_input("Cargo Value (USD)", min_value=100.0, value=10000.0, step=500.0, key="ship_val")
    direction = st.selectbox("Direction", ["Export","Import"], key="ship_dir")

    if st.button("🚢 Calculate Shipment Cost", type="primary", use_container_width=True, key="ship_btn"):
        if not product.strip() or not destination_port.strip():
            st.warning("Enter product and destination port.")
            return
        with st.spinner("📊 Calculating full shipment costs…"):
            from hs_engine import calculate_shipment_cost
            result = calculate_shipment_cost(
                product.strip(), hs_code.strip(), origin_port,
                destination_port.strip(), weight, volume, cargo_val, direction,
            )
            log_trade_usage(user_id=user["id"], email=user["email"],
                            mode="Shipment-Calc", product=product.strip(), result=result)

        if "error" in result:
            st.error(f"❌ {result['error']}")
            return

        frt   = result.get("freight_charges", {})
        orig  = result.get("origin_charges", {})
        dest  = result.get("destination_charges", {})
        ins   = result.get("insurance", {})
        summ  = result.get("total_cost_summary", {})

        c1, c2, c3 = st.columns(3)
        c1.metric("Sea Freight",          f"${frt.get('sea_freight_usd',0):,.0f}")
        c2.metric("Total Origin (INR)",   f"₹{orig.get('total_origin_inr',0):,.0f}")
        c3.metric("Insurance",            f"${ins.get('premium_usd',0):,.0f}")

        st.success(f"**Recommended Mode:** {frt.get('recommended_mode','Sea')} — {frt.get('mode_reason','')}")

        c1, c2 = st.columns(2)
        c1.metric("Export Cost (INR)", f"₹{summ.get('export_cost_inr_approx',0):,.0f}")
        c2.metric("Import Landed Cost (USD)", f"${summ.get('import_landed_cost_usd',0):,.0f}")
        st.info(f"Total landed cost ≈ **{summ.get('cost_as_pct_cargo_value','—')}** of cargo value")

        transit = result.get("transit_time_days", {})
        if transit:
            st.caption(f"⏱ Transit: Sea {transit.get('sea','')} days  ·  Air {transit.get('air','')} days")
        if result.get("notes"):
            st.info(f"💡 {result['notes']}")

        _download_row(result, product, "Shipment-Calc", user["email"])


# ══════════════════════════════════════════════════════════════
# TRADEGPT CHAT TAB
# ══════════════════════════════════════════════════════════════

def tab_tradegpt_chat() -> None:
    user      = st.session_state.user
    rate_info = render_rate_limit_bar()
    st.markdown("## 🤖 TradeGPT — Your AI Trade Advisor")
    st.caption("Ask anything about Indian trade, HS codes, duties, export schemes, compliance, finance, and global markets.")

    if not rate_info["allowed"]:
        st.error("🚫 Daily limit reached.")
        return

    # Suggested starter questions
    starters = [
        "What is the RoDTEP rate for organic turmeric export?",
        "How do I get an Import Export Code (IEC)?",
        "What documents are needed to export to the UAE under CEPA?",
        "Explain the difference between FOB and CIF Incoterms",
        "What is ECGC and how does it protect exporters?",
    ]
    st.caption("**Quick questions:**")
    cols = st.columns(len(starters))
    for i, q in enumerate(starters):
        if cols[i].button(q[:40]+"…" if len(q)>40 else q, key=f"starter_{i}"):
            st.session_state.chat_history.append({"role":"user","content":q})
            with st.spinner("TradeGPT is thinking…"):
                resp = chat_with_tradegpt(q, st.session_state.chat_history[:-1],
                                          st.session_state.get("chat_context"))
                st.session_state.chat_history.append({"role":"assistant","content":resp.get("reply","")})
                log_trade_usage(user_id=user["id"], email=user["email"],
                                mode="TradeGPT", product=q[:100], result=resp)

    st.markdown("---")

    # Chat history display
    for msg in st.session_state.chat_history:
        if msg["role"] == "user":
            st.markdown(f"""
            <div style="background:#0d1117;border:1px solid #30363d;border-radius:10px;
                        padding:12px 16px;margin:6px 0;text-align:right;">
              <span style="color:#e2e8f0;">{msg['content']}</span>
            </div>""", unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div style="background:#1a1a2e;border:1px solid #0f3460;border-radius:10px;
                        padding:12px 16px;margin:6px 0;">
              <span style="color:#a0f0a0;font-size:0.8rem;font-weight:600;">🤖 TradeGPT</span><br>
              <span style="color:#e2e8f0;">{msg['content'].replace(chr(10),'<br>')}</span>
            </div>""", unsafe_allow_html=True)

    # Input box
    user_msg = st.text_input(
        "💬 Ask TradeGPT anything about trade…",
        placeholder="What export incentives are available for spice exporters?",
        key="chat_input",
    )
    c1, c2 = st.columns([5, 1])
    with c2:
        if st.button("Send", type="primary", use_container_width=True, key="chat_send"):
            if user_msg.strip():
                st.session_state.chat_history.append({"role":"user","content":user_msg.strip()})
                with st.spinner("TradeGPT is thinking…"):
                    resp = chat_with_tradegpt(
                        user_msg.strip(),
                        st.session_state.chat_history[:-1],
                        st.session_state.get("chat_context"),
                    )
                    st.session_state.chat_history.append({"role":"assistant","content":resp.get("reply","")})
                    log_trade_usage(user_id=user["id"], email=user["email"],
                                    mode="TradeGPT", product=user_msg[:100], result=resp)

                    if resp.get("follow_up_questions"):
                        st.session_state["_chat_followups"] = resp["follow_up_questions"]
                st.rerun()

    if st.session_state.get("_chat_followups"):
        st.caption("**Suggested follow-ups:**")
        fcols = st.columns(min(len(st.session_state["_chat_followups"]), 3))
        for i, fq in enumerate(st.session_state["_chat_followups"][:3]):
            if fcols[i].button(fq[:45], key=f"followup_{i}_{len(st.session_state.chat_history)}"):
                st.session_state.chat_history.append({"role":"user","content":fq})
                del st.session_state["_chat_followups"]
                with st.spinner("TradeGPT is thinking…"):
                    resp = chat_with_tradegpt(fq, st.session_state.chat_history[:-1])
                    st.session_state.chat_history.append({"role":"assistant","content":resp.get("reply","")})
                st.rerun()

    if st.session_state.chat_history:
        if st.button("🗑️ Clear Chat", key="chat_clear"):
            st.session_state.chat_history = []
            st.session_state.pop("_chat_followups", None)
            st.rerun()


# ══════════════════════════════════════════════════════════════
# AI TRADE REPORTS TAB
# ══════════════════════════════════════════════════════════════

def tab_ai_trade_reports() -> None:
    user      = st.session_state.user
    rate_info = render_rate_limit_bar()
    st.markdown("## 📊 AI Trade Reports")
    st.caption("Generate full trade feasibility reports — executive summary, market analysis, risk, pricing, 90-day action plan.")

    if not rate_info["allowed"]:
        st.error("🚫 Daily limit reached.")
        return

    c1, c2 = st.columns(2)
    with c1:
        product   = st.text_input("📦 Product", placeholder="Organic turmeric powder", key="rpt_prod")
        direction = st.selectbox("Direction", ["Export","Import"], key="rpt_dir")
    with c2:
        countries_raw = st.text_input(
            "Target Markets (comma separated)",
            placeholder="USA, Germany, UAE, Japan, Australia",
            key="rpt_countries",
        )

    if st.button("📊 Generate Full Report", type="primary", use_container_width=True, key="rpt_btn"):
        if not product.strip():
            st.warning("Enter a product.")
            return
        countries = [c.strip() for c in countries_raw.split(",") if c.strip()] or ["USA","UAE","Germany"]
        with st.spinner(f"🤖 Generating comprehensive {direction} report for {product}…"):
            result = generate_ai_trade_report(product.strip(), direction, countries)
            st.session_state.report_result = result
            log_trade_usage(user_id=user["id"], email=user["email"],
                            mode="Trade-Report", product=product.strip(), result=result)

    result = st.session_state.report_result
    if not result or "error" in result:
        if result and "error" in result: st.error(f"❌ {result['error']}")
        return

    st.markdown(f"## 📊 {result.get('report_title','Trade Report')}")

    # Executive Summary
    es = result.get("executive_summary", {})
    if es:
        st.markdown("### 📌 Executive Summary")
        c1, c2 = st.columns(2)
        c1.success(f"**Key Finding:** {es.get('headline_finding','')}")
        c2.info(f"**Opportunity:** {es.get('market_opportunity','')}")
        st.markdown(f"**Recommendation:** {es.get('top_recommendation','')}")
        if es.get("key_risks"):
            st.warning("**Key Risks:** " + " | ".join(es["key_risks"]))

    # Product profile
    pp = result.get("product_profile", {})
    if pp:
        st.markdown("### 📦 Product Profile")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("HS Code",               pp.get("hs_code","—"))
        c2.metric("Global Market",         f"${pp.get('global_market_size_usd_b',0)}B")
        c3.metric("India Export Value",    f"${pp.get('india_export_value_usd_m',0)}M")
        c4.metric("India's Global Rank",   f"#{pp.get('india_global_rank', pp.get('india_rank_globally',0))}")

    # Market by market table
    markets = result.get("market_analysis", [])
    if markets:
        st.markdown("### 🌍 Market Analysis")
        df = pd.DataFrame([{
            "Country":        m.get("country",""),
            "Import Size $M": m.get("import_size_usd_m",0),
            "India Share %":  m.get("india_current_share_pct", m.get("india_share_pct",0)),
            "Growth %":       m.get("growth_rate_pct",0),
            "Opp. Score":     m.get("opportunity_score",0),
            "Entry":          m.get("entry_difficulty",""),
            "Tariff %":       m.get("tariff_pct", m.get("key_tariff_pct",0)),
            "FTA":            m.get("fta_benefit","N/A"),
            "Action":         m.get("recommendation",""),
        } for m in markets])
        st.dataframe(df, use_container_width=True, hide_index=True)

    # Action plan
    ap = result.get("action_plan", [])
    if ap:
        st.markdown("### 📅 90-Day Action Plan")
        for step in ap:
            wk = step.get("week","")
            ac = step.get("action","")
            out = step.get("output","")
            st.markdown(f"**Week {wk}:** {ac}" + (f" → *{out}*" if out else ""))

    # Pricing
    pa = result.get("pricing_analysis", {})
    if pa:
        st.markdown("### 💰 Pricing")
        c1, c2, c3 = st.columns(3)
        c1.metric("India FOB Range",    pa.get("india_fob_range","—") or pa.get("india_fob_range_usd","—"))
        c2.metric("Gross Margin",       pa.get("gross_margin_range_pct","—"))
        c3.metric("Price Trend",        pa.get("price_trend","—"))

    # Risk summary
    rs = result.get("risk_summary", {})
    if rs:
        st.markdown("### ⚠️ Risk Summary")
        st.warning(f"**Overall Risk:** {rs.get('overall','—')}  ·  " + " | ".join(rs.get("top_risks",[])))

    if result.get("disclaimer"):
        st.caption(f"⚠️ {result['disclaimer']}")

    with st.expander("📋 Full Report JSON"):
        st.json(result)

    _download_row(result, product, "Trade-Report", user["email"])


# ══════════════════════════════════════════════════════════════
# MAIN ROUTER
# ══════════════════════════════════════════════════════════════

def main() -> None:
    if not st.session_state.user:
        login_page()
        return

    render_header()
    records  = get_trade_data()
    is_admin = st.session_state.user.get("is_admin", False)

    tab_labels = [
        "🔍 Trade Analysis",
        "🔢 HS Engine",
        "🌍 Market Recs",
        "🔎 Country Lookup",
        "📈 Dashboard",
        "🔮 Future Trends",
        "⚠️ Risk",
        "💰 Price Intel",
        "📄 Doc Analyzer",
        "📋 Compliance",
        "🥊 Competition",
        "💡 Trade Ideas",
        "🔗 Suppliers",
        "🚢 Shipment Calc",
        "🤖 TradeGPT",
        "📊 AI Reports",
        "🎫 Support",
    ]
    if is_admin:
        tab_labels.append("💾 Data Sync")
        tab_labels.append("👤 Admin")

    tabs = st.tabs(tab_labels)

    with tabs[0]:  tab_trade_analysis(records)
    with tabs[1]:  tab_hs_engine()
    with tabs[2]:  tab_market_recommendations(records)
    with tabs[3]:  tab_country_lookup(records)
    with tabs[4]:  tab_dashboard(records)
    with tabs[5]:  tab_future_trends(records)
    with tabs[6]:  tab_risk_analyzer()
    with tabs[7]:  tab_price_intelligence()
    with tabs[8]:  tab_document_analyzer()
    with tabs[9]:  tab_compliance_checker()
    with tabs[10]: tab_competitor_intelligence()
    with tabs[11]: tab_smart_trade_ideas()
    with tabs[12]: tab_supplier_finder()
    with tabs[13]: tab_shipment_calculator()
    with tabs[14]: tab_tradegpt_chat()
    with tabs[15]: tab_ai_trade_reports()
    with tabs[16]: tab_support()
    if is_admin:
        with tabs[17]: tab_data_sync(records)
        with tabs[18]: tab_admin()


if __name__ == "__main__":
    main()