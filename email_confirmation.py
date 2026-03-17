"""
email_confirmation.py
════════════════════════════════════════════════════════════════════
Email Confirmation Handler — Trade Intelligence Engine v1.0

This module handles the post-registration email confirmation flow:
  1. render_confirmation_pending()  — shown right after registration
  2. handle_confirmation_callback() — called on app startup to detect
     Supabase's ?code= or #access_token= URL params
  3. render_confirmed_success()     — shown after successful confirmation

HOW IT WORKS:
  Supabase sends a confirmation email with a magic link.
  When the user clicks it, they are redirected back to your app URL
  with either:
    • ?code=<pkce_code>             (PKCE flow — modern, default)
    • #access_token=<jwt>&...      (implicit flow — legacy)

  This module detects both, exchanges the code/token for a session,
  logs the user in, and shows a beautiful success screen.

SETUP IN SUPABASE DASHBOARD:
  Authentication → URL Configuration
    Site URL:      https://your-app.streamlit.app
    Redirect URLs: https://your-app.streamlit.app/**
  (For local dev add: http://localhost:8501/**)
════════════════════════════════════════════════════════════════════
"""

import streamlit as st
import logging

logger = logging.getLogger("email_confirmation")


# ════════════════════════════════════════════════════════════════════
# STEP 1 — Shown immediately after user registers
# ════════════════════════════════════════════════════════════════════

def render_confirmation_pending(email: str) -> None:
    """
    Show a polished 'Check your inbox' card right after registration.
    Call this instead of (or after) showing the normal success toast.
    """
    st.markdown("""
    <style>
    .confirm-card {
        background: linear-gradient(135deg, #0d1117 0%, #1a2332 100%);
        border: 1px solid #2d4a6b;
        border-radius: 16px;
        padding: 40px 36px;
        max-width: 520px;
        margin: 32px auto;
        text-align: center;
        box-shadow: 0 8px 32px rgba(0,0,0,0.4);
    }
    .confirm-icon { font-size: 56px; margin-bottom: 16px; }
    .confirm-title { color: #63b3ed; font-size: 1.6rem; font-weight: 700; margin-bottom: 12px; }
    .confirm-body  { color: #a0aec0; font-size: 0.95rem; line-height: 1.7; margin-bottom: 20px; }
    .confirm-email { color: #68d391; font-weight: 600; font-size: 1rem; }
    .confirm-steps { text-align: left; background: #0a0f1e; border-radius: 10px;
                     padding: 16px 20px; margin-top: 20px; }
    .confirm-steps li { color: #e2e8f0; font-size: 0.88rem; margin-bottom: 6px; }
    .confirm-note  { color: #4a5568; font-size: 0.78rem; margin-top: 16px; }
    </style>
    """, unsafe_allow_html=True)

    st.markdown(f"""
    <div class="confirm-card">
      <div class="confirm-icon">📧</div>
      <div class="confirm-title">Check Your Inbox</div>
      <div class="confirm-body">
        A confirmation link has been sent to:<br>
        <span class="confirm-email">{email}</span><br><br>
        Click the link in the email to activate your account and start trading smarter.
      </div>
      <div class="confirm-steps">
        <ol>
          <li>Open your email inbox (check spam/junk too)</li>
          <li>Find the email from <strong>Trade Intelligence Engine</strong></li>
          <li>Click <strong>"Confirm your email"</strong></li>
          <li>You'll be redirected back here and automatically signed in</li>
        </ol>
      </div>
      <div class="confirm-note">
        Didn't receive it? Wait 1–2 minutes. Free email services (Gmail, Yahoo) are instant.<br>
        Corporate emails may take up to 5 minutes. The link expires in 24 hours.
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Resend button (uses Supabase's built-in resend — rate limited to 1/min)
    st.markdown("<br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("🔄 Resend Confirmation Email", use_container_width=True, key="resend_confirm_btn"):
            _resend_confirmation(email)


def _resend_confirmation(email: str) -> None:
    """Trigger a new confirmation email via Supabase."""
    try:
        from supabase_service import supabase_auth
        supabase_auth.auth.resend({"type": "signup", "email": email})
        st.success("✅ New confirmation email sent! Check your inbox.")
    except Exception as e:
        msg = str(e).lower()
        if "rate" in msg or "429" in msg or "too many" in msg:
            st.warning("⏳ Please wait 60 seconds before requesting another email.")
        else:
            st.error(f"Could not resend — {type(e).__name__}. Try again in a moment.")
        logger.warning(f"resend_confirmation failed for {email}: {e}")


# ════════════════════════════════════════════════════════════════════
# STEP 2 — Called on every app startup to detect confirmation callback
# ════════════════════════════════════════════════════════════════════

def handle_confirmation_callback() -> bool:
    """
    Detect if the current page load is a Supabase email-confirmation redirect.

    Call this at the TOP of app.py main(), BEFORE rendering any page:

        from email_confirmation import handle_confirmation_callback
        if handle_confirmation_callback():
            st.stop()  # stop here; success screen was already shown

    Returns True  if a confirmation was detected and handled (render stopped).
    Returns False if this is a normal page load — continue as usual.
    """
    params = st.query_params

    # ── PKCE flow: ?code=<auth_code> ─────────────────────────────
    code = params.get("code", "")
    if code:
        _handle_pkce_code(code)
        return True

    # ── Implicit flow: fragment params (Streamlit sees them as query) ─
    # Supabase may pass: ?access_token=...&refresh_token=...&type=signup
    access_token  = params.get("access_token", "")
    token_type    = params.get("type", "")
    if access_token and token_type in ("signup", "magiclink", "recovery", "email_change", ""):
        _handle_token(access_token, params.get("refresh_token", ""))
        return True

    return False


def _handle_pkce_code(code: str) -> None:
    """Exchange PKCE auth code for a session and log the user in."""
    with st.spinner("Confirming your email…"):
        from supabase_service import exchange_code_for_session, get_user_role, log_auth_action
        result = exchange_code_for_session(code)

    # Clear the ?code= from URL so refresh doesn't replay
    st.query_params.clear()

    if result.get("status") == "success":
        _auto_login_after_confirm(
            access_token=result["access_token"],
            refresh_token=result.get("refresh_token", ""),
            user_data=result.get("user", {}),
        )
    else:
        _render_confirm_error(result.get("message", "Confirmation failed."))


def _handle_token(access_token: str, refresh_token: str) -> None:
    """Handle implicit-flow token from URL fragment."""
    with st.spinner("Confirming your email…"):
        from supabase_service import login_with_token
        result = login_with_token(access_token, refresh_token)

    st.query_params.clear()

    if result.get("status") == "success":
        _auto_login_after_confirm(
            access_token=access_token,
            refresh_token=refresh_token,
            user_data=result.get("user", {}),
        )
    else:
        _render_confirm_error(result.get("message", "Token verification failed."))


def _auto_login_after_confirm(access_token: str, refresh_token: str, user_data: dict) -> None:
    """
    Store the confirmed user in session state (same structure as login_user)
    then show the success screen.
    """
    from supabase_service import get_user_role, ADMIN_EMAILS

    email   = user_data.get("email", "")
    user_id = user_data.get("id", "")
    role    = user_data.get("role") or get_user_role(user_id) or "free"
    is_admin = email.strip() in ADMIN_EMAILS or role == "admin"

    # Write into session state — same keys app.py uses after normal login
    st.session_state.user = {
        "id":           user_id,
        "email":        email,
        "role":         "admin" if is_admin else role,
        "is_admin":     is_admin,
        "access_token": access_token,
    }
    st.session_state.authenticated  = True
    st.session_state.just_confirmed = True   # flag so app.py can show congrats banner

    # Clear any stale rate-limit cache so it re-reads from DB
    st.session_state.pop("rate_info", None)
    st.session_state.pop("_ql_live",  None)

    logger.info(f"Email confirmed and auto-logged in: {email}")
    render_confirmed_success(email, role)


# ════════════════════════════════════════════════════════════════════
# STEP 3 — Shown after successful confirmation
# ════════════════════════════════════════════════════════════════════

def render_confirmed_success(email: str, role: str = "free") -> None:
    """
    Display a polished confirmation success screen with balloons.
    The user is already logged in (session state is set) when this runs.
    """
    st.balloons()

    role_labels = {
        "free":    ("Free Plan", "10 queries/day", "#68d391"),
        "user":    ("Standard Plan", "50 queries/day", "#63b3ed"),
        "analyst": ("Analyst Plan", "150 queries/day", "#f6ad55"),
        "pro":     ("Pro Plan", "500 queries/day", "#fc8181"),
        "admin":   ("Admin Access", "Unlimited", "#e9d8fd"),
    }
    label, quota, color = role_labels.get(role, ("Free Plan", "10 queries/day", "#68d391"))

    st.markdown("""
    <style>
    .success-card {
        background: linear-gradient(135deg, #0d1117 0%, #1a2d1a 100%);
        border: 1px solid #276749;
        border-radius: 16px;
        padding: 44px 40px;
        max-width: 540px;
        margin: 28px auto;
        text-align: center;
        box-shadow: 0 8px 40px rgba(72,187,120,0.15);
    }
    .success-icon  { font-size: 64px; margin-bottom: 18px; }
    .success-title { color: #68d391; font-size: 1.8rem; font-weight: 700; margin-bottom: 10px; }
    .success-sub   { color: #a0aec0; font-size: 1rem; margin-bottom: 24px; }
    .success-email { color: #e2e8f0; font-weight: 600; }
    .plan-badge {
        display: inline-block;
        padding: 6px 18px;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 600;
        margin-bottom: 24px;
    }
    .feature-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 10px;
        margin: 20px 0;
        text-align: left;
    }
    .feature-item {
        background: #0a0f1e;
        border-radius: 8px;
        padding: 10px 14px;
        color: #e2e8f0;
        font-size: 0.82rem;
    }
    .feature-item .fi-icon { margin-right: 6px; }
    .success-cta { color: #4a5568; font-size: 0.82rem; margin-top: 18px; }
    </style>
    """, unsafe_allow_html=True)

    st.markdown(f"""
    <div class="success-card">
      <div class="success-icon">🎉</div>
      <div class="success-title">Email Confirmed!</div>
      <div class="success-sub">
        Welcome to the <strong>Indian Trade Intelligence Engine</strong>.<br>
        You're signed in as <span class="success-email">{email}</span>
      </div>
      <div class="plan-badge" style="background:{color}22;color:{color};border:1px solid {color}44;">
        {label} · {quota}
      </div>
      <div class="feature-grid">
        <div class="feature-item"><span class="fi-icon">🔍</span>HS Code Mapper</div>
        <div class="feature-item"><span class="fi-icon">⚖️</span>Risk Analyzer</div>
        <div class="feature-item"><span class="fi-icon">💰</span>Price Intelligence</div>
        <div class="feature-item"><span class="fi-icon">📋</span>Compliance Checker</div>
        <div class="feature-item"><span class="fi-icon">🌍</span>Market Scout</div>
        <div class="feature-item"><span class="fi-icon">🤝</span>Supplier Finder</div>
        <div class="feature-item"><span class="fi-icon">💡</span>Smart Trade Ideas</div>
        <div class="feature-item"><span class="fi-icon">📄</span>Document Analyzer</div>
      </div>
      <div class="success-cta">Click "Continue to Dashboard" below to start your first trade analysis</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("🚀 Continue to Dashboard", use_container_width=True, type="primary", key="confirm_continue_btn"):
            # Clear the flag and rerun into normal app flow
            st.session_state.pop("just_confirmed", None)
            st.rerun()


# ════════════════════════════════════════════════════════════════════
# ERROR SCREEN
# ════════════════════════════════════════════════════════════════════

def _render_confirm_error(message: str) -> None:
    """Show a friendly error if confirmation link is broken/expired."""
    st.markdown("""
    <style>
    .err-card {
        background: linear-gradient(135deg, #0d1117 0%, #2d1a1a 100%);
        border: 1px solid #742a2a;
        border-radius: 16px;
        padding: 40px 36px;
        max-width: 500px;
        margin: 32px auto;
        text-align: center;
    }
    .err-icon  { font-size: 52px; margin-bottom: 14px; }
    .err-title { color: #fc8181; font-size: 1.5rem; font-weight: 700; margin-bottom: 10px; }
    .err-body  { color: #a0aec0; font-size: 0.92rem; line-height: 1.7; }
    </style>
    """, unsafe_allow_html=True)

    st.markdown(f"""
    <div class="err-card">
      <div class="err-icon">⚠️</div>
      <div class="err-title">Confirmation Failed</div>
      <div class="err-body">
        {message}<br><br>
        This usually means the link has <strong>expired</strong> (links are valid for 24 hours)
        or has already been used.<br><br>
        Try registering again or contact support.
      </div>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("← Back to Sign In", use_container_width=True, key="confirm_err_back_btn"):
            st.query_params.clear()
            st.rerun()


# ════════════════════════════════════════════════════════════════════
# INTEGRATION SNIPPET FOR app.py
# ════════════════════════════════════════════════════════════════════
# Add this to the TOP of your main() function in app.py, BEFORE any
# page routing:
#
#   from email_confirmation import handle_confirmation_callback
#
#   def main():
#       # ── Email confirmation callback (must be first) ────────────
#       if handle_confirmation_callback():
#           st.stop()
#       ...rest of your routing...
#
# And in your register form handler (where you call sign_up_user):
#
#   result = sign_up_user(email, password, role)
#   if result["status"] == "success":
#       from email_confirmation import render_confirmation_pending
#       render_confirmation_pending(email)
#       st.stop()
#   else:
#       st.error(result["message"])
# ════════════════════════════════════════════════════════════════════