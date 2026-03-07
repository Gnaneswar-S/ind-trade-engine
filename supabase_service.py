"""
supabase_service.py
Production-grade Supabase integration
Features: Auth, Admin panel, Rate limiting, Email alerts, Usage tracking
"""

import os
import smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL  = os.getenv("SUPABASE_URL")
SUPABASE_KEY  = os.getenv("SUPABASE_SERVICE_KEY")   # service_role key
SUPABASE_ANON = os.getenv("SUPABASE_ANON_KEY")      # anon key (required for PKCE)

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("❌ Supabase credentials missing in .env")

# Service-role client — server-side DB ops, bypasses RLS
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Anon client — user-facing auth, PKCE flow, password reset
# PKCE requires anon key. Falls back to service key if anon not configured.
_anon_key = SUPABASE_ANON if SUPABASE_ANON else SUPABASE_KEY
supabase_auth: Client = create_client(SUPABASE_URL, _anon_key)

# Rate limit config (queries per day per role)
RATE_LIMITS = {
    "free":  10,
    "user":  50,
    "pro":   200,
    "admin": 99999,
}

ADMIN_EMAILS = os.getenv("ADMIN_EMAILS", "").split(",")  # comma-separated in .env


# ═══════════════════════════════════════════
# AUTH FUNCTIONS (FIXED)
# ═══════════════════════════════════════════

def sign_up_user(email: str, password: str, role: str = "free") -> dict:
    """Register a new user. Default role = 'free' (rate-limited)."""
    try:
        response = supabase.auth.sign_up({
            "email": email,
            "password": password,
            "options": {"data": {"role": role}},
        })

        if not response.user:
            return {"status": "error", "message": "User creation failed"}

        user = response.user

        supabase.table("profiles").upsert(
            {"user_id": user.id, "email": email, "role": role},
            on_conflict="user_id",
        ).execute()

        log_auth_action(user.id, email, "REGISTER")

        return {
            "status": "success",
            "user": {"id": user.id, "email": user.email, "role": role},
            "email_confirmation_required": user.confirmed_at is None,
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}


def login_user(email: str, password: str) -> dict:
    """Authenticate with email + password."""
    try:
        response = supabase.auth.sign_in_with_password({
            "email": email,
            "password": password,
        })

        if not response.user:
            return {"status": "error", "message": "Invalid credentials"}

        user     = response.user
        role     = get_user_role(user.id)
        is_admin = email.strip() in [e.strip() for e in ADMIN_EMAILS] or role == "admin"

        log_auth_action(user.id, email, "LOGIN")

        return {
            "status": "success",
            "user": {
                "id":           user.id,
                "email":        user.email,
                "role":         "admin" if is_admin else role,
                "is_admin":     is_admin,
                "access_token": response.session.access_token if response.session else None,
            },
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}


def login_with_token(access_token: str, refresh_token: str = "") -> dict:
    """
    Auto-login after email confirmation.
    Supabase sends tokens in URL hash → JS converts to query params → we read here.
    """
    try:
        # Use get_user with the token directly (more reliable than set_session)
        user_resp = supabase.auth.get_user(access_token)

        if not user_resp or not user_resp.user:
            # Fallback: try set_session
            session = supabase.auth.set_session(access_token, refresh_token)
            if not session or not session.user:
                return {"status": "error", "message": "Token is invalid or expired. Please log in manually."}
            user = session.user
        else:
            user = user_resp.user

        role     = get_user_role(user.id)
        is_admin = (user.email or "").strip() in [e.strip() for e in ADMIN_EMAILS] or role == "admin"

        # Ensure profile exists (first-time confirmation)
        supabase.table("profiles").upsert(
            {"user_id": user.id, "email": user.email, "role": role or "free"},
            on_conflict="user_id",
        ).execute()

        log_auth_action(user.id, user.email, "EMAIL_CONFIRMED_LOGIN")

        return {
            "status": "success",
            "user": {
                "id":       user.id,
                "email":    user.email,
                "role":     "admin" if is_admin else (role or "free"),
                "is_admin": is_admin,
                "access_token": access_token,
            },
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}


def logout_user(user_id: str, email: str) -> dict:
    try:
        log_auth_action(user_id, email, "LOGOUT")
        supabase.auth.sign_out()
        return {"status": "success"}
    except Exception as e:
        return {"status": "success", "warning": str(e)}


def get_user_role(user_id: str) -> str:
    try:
        resp = (
            supabase.table("profiles")
            .select("role")
            .eq("user_id", user_id)
            .single()
            .execute()
        )
        return (resp.data or {}).get("role", "free")
    except Exception:
        return "free"


# ═══════════════════════════════════════════
# RATE LIMITING
# ═══════════════════════════════════════════

def check_rate_limit(user_id: str, role: str) -> dict:
    """
    Check if user has exceeded their daily query limit.
    Returns: {"allowed": bool, "used": int, "limit": int, "reset_at": str}
    """
    limit = RATE_LIMITS.get(role, RATE_LIMITS["free"])

    try:
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

        resp = (
            supabase.table("trade_usage_logs")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .gte("timestamp", today_start)
            .execute()
        )

        used = resp.count if resp.count is not None else len(resp.data or [])
        reset_at = (datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
                    + timedelta(days=1)).strftime("%Y-%m-%d 00:00 UTC")

        return {
            "allowed":  used < limit,
            "used":     used,
            "limit":    limit,
            "reset_at": reset_at,
            "remaining": max(0, limit - used),
        }

    except Exception as e:
        # On error, allow the query (fail open)
        return {"allowed": True, "used": 0, "limit": limit, "remaining": limit, "reset_at": "unknown"}


# ═══════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════

def log_auth_action(user_id: str, email: str, action: str):
    try:
        supabase.table("auth_logs").insert({
            "user_id":   user_id,
            "email":     email,
            "action":    action,
            "timestamp": datetime.utcnow().isoformat(),
        }).execute()
    except Exception:
        pass


def log_trade_usage(user_id: str, email: str, mode: str, product: str, result: dict = None) -> dict:
    """
    Log a trade query. Returns {"status":"success"} or {"status":"error","message":...}.
    Caller should surface errors to the admin if needed.
    """
    try:
        data = {
            "user_id":   user_id,
            "email":     email,
            "mode":      mode,
            "product":   product[:500] if product else "",
            "timestamp": datetime.utcnow().isoformat(),
        }
        if result and isinstance(result, dict) and "hs_code" in result:
            data["hs_code"] = str(result["hs_code"])[:50]
        supabase.table("trade_usage_logs").insert(data).execute()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ═══════════════════════════════════════════
# STATS
# ═══════════════════════════════════════════

def get_user_stats(user_id: str) -> dict:
    try:
        trade_logs = (
            supabase.table("trade_usage_logs")
            .select("mode, timestamp")
            .eq("user_id", user_id)
            .execute()
        )
        auth_logs = (
            supabase.table("auth_logs")
            .select("action")
            .eq("user_id", user_id)
            .execute()
        )

        logs        = trade_logs.data or []
        total_q     = len(logs)
        total_login = len([l for l in (auth_logs.data or []) if l["action"] == "LOGIN"])
        by_mode     = {}
        for l in logs:
            by_mode[l.get("mode", "Unknown")] = by_mode.get(l.get("mode", "Unknown"), 0) + 1

        return {
            "status":        "success",
            "total_queries": total_q,
            "total_logins":  total_login,
            "by_mode":       by_mode,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ═══════════════════════════════════════════
# ADMIN FUNCTIONS
# ═══════════════════════════════════════════

def get_all_users() -> list[dict]:
    """Admin: get all profiles with usage counts."""
    try:
        profiles = supabase.table("profiles").select("*").execute()
        users    = profiles.data or []

        for u in users:
            try:
                logs = (
                    supabase.table("trade_usage_logs")
                    .select("id", count="exact")
                    .eq("user_id", u["user_id"])
                    .execute()
                )
                u["total_queries"] = logs.count or 0
            except Exception:
                u["total_queries"] = 0

        return sorted(users, key=lambda x: x.get("total_queries", 0), reverse=True)
    except Exception as e:
        return []


def get_all_queries(limit: int = 100) -> tuple:
    """Admin: get (queries_list, error_message) — never silently returns empty."""
    try:
        resp = (
            supabase.table("trade_usage_logs")
            .select("*")
            .order("timestamp", desc=True)
            .limit(limit)
            .execute()
        )
        return (resp.data or []), None
    except Exception as e:
        return [], str(e)


def update_user_role(user_id: str, new_role: str) -> dict:
    """Admin: upgrade/downgrade a user's role."""
    valid_roles = ["free", "user", "pro", "admin"]
    if new_role not in valid_roles:
        return {"status": "error", "message": f"Role must be one of {valid_roles}"}
    try:
        supabase.table("profiles").update({"role": new_role}).eq("user_id", user_id).execute()
        return {"status": "success"}
    except Exception as e:
        msg = str(e)
        # Detect Postgres check constraint violation (code 23514)
        if "23514" in msg or "profiles_role_check" in msg or "check constraint" in msg.lower():
            return {
                "status": "error",
                "message": (
                    f"Database role constraint is outdated — it does not allow '{new_role}' yet.\n\n"
                    "Fix: Run fix_rls_and_tables.sql in Supabase → SQL Editor.\n"
                    "Look for the section: '-- FIX: Role constraint'"
                )
            }
        return {"status": "error", "message": msg}


def get_platform_stats() -> dict:
    """Admin: platform-wide stats. Returns _error key if anything fails."""
    errors = []
    total_users_count = 0
    total_queries_count = 0
    queries_today_count = 0
    by_mode = {}

    try:
        r = supabase.table("profiles").select("user_id", count="exact").execute()
        total_users_count = r.count or 0
    except Exception as e:
        errors.append(f"profiles: {e}")

    try:
        r = supabase.table("trade_usage_logs").select("id", count="exact").execute()
        total_queries_count = r.count or 0
    except Exception as e:
        errors.append(f"trade_usage_logs count: {e}")

    try:
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        r = (
            supabase.table("trade_usage_logs")
            .select("id", count="exact")
            .gte("timestamp", today_start)
            .execute()
        )
        queries_today_count = r.count or 0
    except Exception as e:
        errors.append(f"queries_today: {e}")

    try:
        r = supabase.table("trade_usage_logs").select("mode").execute()
        for l in (r.data or []):
            m = l.get("mode", "Unknown")
            by_mode[m] = by_mode.get(m, 0) + 1
    except Exception as e:
        errors.append(f"by_mode: {e}")

    return {
        "total_users":   total_users_count,
        "total_queries": total_queries_count,
        "queries_today": queries_today_count,
        "by_mode":       by_mode,
        "_errors":       errors if errors else None,
    }


# ═══════════════════════════════════════════
# EMAIL ALERTS
# ═══════════════════════════════════════════

def send_email_alert(to_email: str, subject: str, body_html: str) -> dict:
    """
    Send an email alert via SMTP.
    Requires in .env:
        SMTP_HOST=smtp.gmail.com
        SMTP_PORT=587
        SMTP_USER=your@gmail.com
        SMTP_PASS=your_app_password   (Gmail App Password, not account password)
        SMTP_FROM=your@gmail.com
    """
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    smtp_from = os.getenv("SMTP_FROM", smtp_user)

    if not smtp_user or not smtp_pass:
        return {"status": "error", "message": "SMTP credentials not configured in .env"}

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = smtp_from
        msg["To"]      = to_email
        msg.attach(MIMEText(body_html, "html"))

        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_from, to_email, msg.as_string())

        return {"status": "success"}

    except smtplib.SMTPAuthenticationError:
        return {
            "status": "error",
            "message": (
                f"Gmail authentication failed for {smtp_user}.\n"
                "You must use a Gmail App Password, NOT your Gmail account password.\n"
                "Steps: Google Account → Security → 2-Step Verification → App Passwords → Create one"
            )
        }
    except smtplib.SMTPConnectError as e:
        return {"status": "error",
                "message": f"Cannot connect to {smtp_host}:{smtp_port}. Check SMTP_HOST and SMTP_PORT in .env. ({e})"}
    except smtplib.SMTPRecipientsRefused as e:
        return {"status": "error", "message": f"Recipient address rejected: {to_email}. ({e})"}
    except Exception as e:
        return {"status": "error", "message": f"SMTP error: {e}"}


def notify_all_users_new_dataset(dataset_name: str = "Trade Map 2024") -> dict:
    """
    Send email alerts to all registered users about a new dataset.
    Called from the admin panel.
    """
    try:
        profiles = supabase.table("profiles").select("email").execute()
        emails   = [p["email"] for p in (profiles.data or []) if p.get("email")]

        subject = f"🇮🇳 Trade Intelligence Engine — New Dataset Available: {dataset_name}"
        body    = f"""
        <html><body style="font-family:Arial,sans-serif;max-width:600px;margin:auto;">
        <h2 style="color:#1a4f7a;">📦 New Trade Data Available</h2>
        <p>The <strong>{dataset_name}</strong> dataset has been uploaded to your
        Trade Intelligence Engine.</p>
        <ul>
          <li>✅ Updated market recommendations</li>
          <li>✅ Fresh country-level trade stats</li>
          <li>✅ Revised opportunity and trend scores</li>
        </ul>
        <p>
          <a href="http://localhost:8501" style="background:#1a4f7a;color:white;
          padding:10px 20px;border-radius:5px;text-decoration:none;">
          Open Trade Intelligence Engine →
          </a>
        </p>
        <p style="color:#888;font-size:12px;">
          You are receiving this because you have an account on the Trade Intelligence Engine.
        </p>
        </body></html>
        """

        sent, failed = 0, 0
        for email in emails:
            result = send_email_alert(email, subject, body)
            if result["status"] == "success":
                sent += 1
            else:
                failed += 1

        return {"status": "success", "sent": sent, "failed": failed, "total": len(emails)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ═══════════════════════════════════════════
# FORGOT PASSWORD  (OTP-based — no redirect links)
# ═══════════════════════════════════════════
#
# ARCHITECTURE: We bypass Supabase email links entirely.
#
# Why: Supabase reset links put tokens in the URL #hash fragment.
#   Hash is browser-only — Python/Streamlit can never read it.
#   No JS bridge works reliably inside Streamlit's sandboxed environment.
#
# Solution: Our own OTP flow (already used for 2FA):
#   1. User enters email on Forgot Password tab
#   2. We send a 6-digit OTP via SMTP (otp_service.py)
#   3. User enters OTP in-app → verified against Supabase otp_store
#   4. We use Supabase Admin API (service_role) to update password directly
#      No tokens, no redirects, no hash fragments needed.
#
# admin_update_user_password() uses the service_role key which can update
# any user's password without the user's session — this is the Admin API.

def smtp_diagnostic() -> dict:
    """
    Test SMTP configuration and return a detailed status report.
    Called from the UI to help debug email delivery issues.
    """
    smtp_host = os.getenv("SMTP_HOST", "")
    smtp_port = os.getenv("SMTP_PORT", "587")
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")

    issues = []
    if not smtp_host: issues.append("SMTP_HOST not set in .env")
    if not smtp_user: issues.append("SMTP_USER not set in .env")
    if not smtp_pass: issues.append("SMTP_PASS not set in .env")
    if issues:
        return {"status": "error", "message": "Missing config: " + " | ".join(issues)}

    try:
        import smtplib
        with smtplib.SMTP(smtp_host, int(smtp_port), timeout=8) as s:
            s.ehlo()
            s.starttls()
            s.login(smtp_user, smtp_pass)
        return {"status": "success",
                "message": f"Connected to {smtp_host}:{smtp_port} as {smtp_user}"}
    except smtplib.SMTPAuthenticationError:
        return {"status": "error",
                "message": (
                    f"Authentication failed for {smtp_user}.\n"
                    "For Gmail: use an App Password (not your account password).\n"
                    "Go to: myaccount.google.com → Security → 2-Step → App Passwords"
                )}
    except smtplib.SMTPConnectError as e:
        return {"status": "error", "message": f"Cannot connect to {smtp_host}:{smtp_port} — {e}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def request_password_reset(email: str) -> dict:
    """
    Initiate OTP-based password reset.
    Sends a 6-digit code to the email via SMTP.
    Returns real errors so the UI can show them to the user.
    """
    from otp_service import send_otp_email as _send_otp

    # 1. Verify SMTP is configured before doing anything
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")
    if not smtp_user or not smtp_pass:
        return {
            "status": "error",
            "message": (
                "Email sending is not configured.\n"
                "Add SMTP_USER and SMTP_PASS to your .env file.\n"
                "See SETUP.md for Gmail App Password instructions."
            )
        }

    # 2. Check if this email exists in our system
    try:
        profiles = supabase.table("profiles").select("email").eq("email", email).execute()
        if not profiles.data:
            # Return success anyway — don't reveal if email exists
            return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": f"Database error: {e}"}

    # 3. Send the OTP — propagate any SMTP error to the caller
    result = _send_otp(email, email.split("@")[0])
    return result  # {"status": "success"} or {"status": "error", "message": "..."}


def verify_reset_otp(email: str, otp: str) -> dict:
    """
    Verify the OTP entered by user during password reset.
    Returns {"status": "success"} or {"status": "error", "message": "..."}
    """
    from otp_service import verify_otp as _verify
    return _verify(email, otp)


def admin_update_user_password(email: str, new_password: str) -> dict:
    """
    Update a user's password using Supabase Admin API (service_role key).
    Called AFTER OTP is verified — no user session or token needed.

    This uses the admin endpoint which bypasses all auth flow complications:
    no redirect links, no hash fragments, no PKCE, no browser issues.
    """
    if len(new_password) < 6:
        return {"status": "error", "message": "Password must be at least 6 characters"}
    try:
        import requests as _req
        headers = {
            "apikey":        SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type":  "application/json",
        }
        # Step 1: find user ID from email via admin users list
        resp = _req.get(
            f"{SUPABASE_URL}/auth/v1/admin/users?page=1&per_page=1000",
            headers=headers,
            timeout=10,
        )
        if resp.status_code != 200:
            return {"status": "error", "message": f"Could not fetch users: {resp.text}"}

        data  = resp.json()
        users = data.get("users", [])
        uid   = None
        for u in users:
            if (u.get("email") or "").lower() == email.lower():
                uid = u.get("id")
                break

        if not uid:
            return {"status": "error", "message": "Email not found in system."}

        # Step 2: update password via admin endpoint
        upd = _req.put(
            f"{SUPABASE_URL}/auth/v1/admin/users/{uid}",
            headers=headers,
            json={"password": new_password},
            timeout=10,
        )
        if upd.status_code in (200, 201):
            return {"status": "success"}
        else:
            return {"status": "error", "message": f"Update failed: {upd.text}"}

    except Exception as e:
        return {"status": "error", "message": str(e)}


# Keep for backwards compatibility / email confirmation flow
def exchange_code_for_session(code: str) -> dict:
    """Exchange PKCE auth code for session (used for email confirmation)."""
    try:
        _anon_key = SUPABASE_ANON if SUPABASE_ANON else SUPABASE_KEY
        auth_client = create_client(SUPABASE_URL, _anon_key)
        resp = auth_client.auth.exchange_code_for_session({"auth_code": code})
        if not resp or not resp.session:
            return {"status": "error", "message": "Invalid or expired link."}
        return {
            "status":        "success",
            "access_token":  resp.session.access_token,
            "refresh_token": resp.session.refresh_token or "",
            "user": {"id": resp.user.id, "email": resp.user.email},
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def update_user_password(access_token: str, new_password: str) -> dict:
    """Legacy: update password with an active access token (kept for compatibility)."""
    if len(new_password) < 6:
        return {"status": "error", "message": "Password must be at least 6 characters"}
    try:
        _anon_key = SUPABASE_ANON if SUPABASE_ANON else SUPABASE_KEY
        auth_client = create_client(SUPABASE_URL, _anon_key)
        auth_client.auth.set_session(access_token, "")
        auth_client.auth.update_user({"password": new_password})
        try:
            auth_client.auth.sign_out()
        except Exception:
            pass
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def notify_user_limit_warning(user_id: str, email: str, used: int, limit: int):
    """Warn a user when they hit 80% of their daily limit."""
    if used == int(limit * 0.8):
        subject = "⚠️ Trade Intelligence — Query Limit Warning"
        body    = f"""
        <html><body style="font-family:Arial,sans-serif;">
        <h3>⚠️ You've used {used} of {limit} daily queries</h3>
        <p>You have <strong>{limit - used} queries remaining</strong> today.</p>
        <p>Your limit resets at midnight UTC.</p>
        <p>To increase your limit, contact the administrator.</p>
        </body></html>
        """
        send_email_alert(email, subject, body)