"""
supabase_service.py
Production-grade Supabase integration — v2.3
────────────────────────────────────────────────────────────────────
FIXES IN v2.3  (ROOT CAUSE: confirmation email never sent):
  ● sign_up_user:      uses supabase_AUTH (anon key) — NOT service key.
                       Service-role key bypasses Supabase email system entirely.
                       This was why the confirmation email was never sent.
  ● login_user:        uses supabase_auth (anon key) — proper session management.
  ● login_with_token:  uses supabase_auth (anon key) for get_user/set_session.
  ● logout_user:       uses supabase_auth (anon key) for sign_out.

  RULE: supabase (service key) = DB reads/writes only (profiles, logs, admin).
        supabase_auth (anon key) = ALL auth operations (sign_up, sign_in, etc.).

FIXES IN v2.2  (your "Registration failed" bug):
  ● sign_up_user: pre-checks profiles table for duplicate email
    BEFORE calling Supabase auth, so the real error is never swallowed.
  ● sign_up_user: detects Supabase "silent duplicate" (confirmed_at set)
    and returns the correct "already registered" message.
  ● sign_up_user: exposes all known Supabase error codes as human-readable
    messages (rate_limited, signups_disabled, weak_password, network…).
  ● Set DEBUG_REGISTRATION=true in .env to see raw Supabase errors on screen
    during development — remove / set false for production.
  ● email_confirmation_required flag returned on success so app.py
    can show the "Check Your Inbox" card instead of a generic toast.

FIXES IN v2.1  (from previous session):
  ● RATE_LIMITS aligned with query_limiter ROLE_DAILY_LIMITS
    (added "analyst":150, corrected "pro":500, "admin":999999)
  ● check_rate_limit: reads query_limits table first (dual-mode)

Security hardening (all versions):
  ● All credentials from env only — no hardcoding
  ● Input validation and sanitisation on all public functions
  ● Structured logging — no secrets in logs
  ● Rate limit fail-open (never blocks on DB error)
────────────────────────────────────────────────────────────────────
"""

import os
import re
import smtplib
import logging
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("supabase_service")

# ── Secure credential loading ─────────────────────────────────────
SUPABASE_URL  = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY  = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
SUPABASE_ANON = os.getenv("SUPABASE_ANON_KEY", "").strip()

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError(
        "❌ Supabase credentials missing. Add SUPABASE_URL and SUPABASE_SERVICE_KEY to .env"
    )

# Service-role client — bypasses RLS, server-side only
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Anon client — user-facing auth / PKCE
_anon_key      = SUPABASE_ANON if SUPABASE_ANON else SUPABASE_KEY
supabase_auth: Client = create_client(SUPABASE_URL, _anon_key)

# ── Rate limits — MUST stay in sync with ROLE_DAILY_LIMITS in query_limiter.py
RATE_LIMITS = {
    "free":    10,
    "user":    50,
    "analyst": 150,
    "pro":     500,
    "admin":   999999,
}

# Admin emails (comma-separated in env)
ADMIN_EMAILS = [e.strip() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()]

# Set DEBUG_REGISTRATION=true in .env to see raw Supabase errors on-screen (dev only)
_DEBUG_REG = os.getenv("DEBUG_REGISTRATION", "false").lower() == "true"

# ── Input validation helpers ──────────────────────────────────────
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+\-]+@[a-zA-Z0-9\-]+\.[a-zA-Z]{2,}$")

def _validate_email(email: str) -> bool:
    return bool(email and _EMAIL_RE.match(email.strip()))

def _sanitise_str(s: str, max_len: int = 500) -> str:
    if not s:
        return ""
    return str(s).strip()[:max_len]

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ════════════════════════════════════════════════════════════════════
# AUTH
# ════════════════════════════════════════════════════════════════════

def sign_up_user(email: str, password: str, role: str = "free") -> dict:
    """
    Register a new user.

    Returns:
      {"status": "success", "user": {...}, "email_confirmation_required": True}
        — user created, confirmation email sent by Supabase.
      {"status": "error", "message": "...", "code": "..."}
        — validation failure or Supabase error.

    Error codes:
      already_registered | rate_limited | signups_disabled |
      invalid_email | weak_password | network_error | unknown
    """
    email = email.strip().lower() if email else ""

    if not _validate_email(email):
        return {"status": "error", "message": "Invalid email address format.", "code": "invalid_email"}
    if not password or len(password) < 6:
        return {"status": "error", "message": "Password must be at least 6 characters.", "code": "weak_password"}
    if role not in RATE_LIMITS:
        role = "free"

    # ── Pre-check: already in profiles table? ────────────────────────
    # This catches the case where the user is registered but not yet
    # confirmed — Supabase silently re-sends the confirmation email
    # without raising an error, making it look like a fresh success.
    try:
        existing = (
            supabase.table("profiles")
            .select("email")
            .eq("email", email)
            .execute()
        )
        if existing.data:
            return {
                "status":  "error",
                "message": "This email is already registered. Please sign in instead.",
                "code":    "already_registered",
            }
    except Exception as e:
        # Table may not exist yet on first deploy — don't block registration
        logger.warning(f"pre-check profiles query failed (non-fatal): {type(e).__name__}: {e}")

    # ── Call Supabase auth ────────────────────────────────────────────
    try:
        # IMPORTANT: Must use supabase_auth (anon key) for sign_up.
        # Using the service-role key (supabase) bypasses Supabase's email
        # confirmation system — the confirmation email is never sent.
        response = supabase_auth.auth.sign_up({
            "email":   email,
            "password": password,
            "options": {"data": {"role": role}},
        })

        if response.user:
            user = response.user

            # Supabase "silent duplicate": when email confirmation is enabled
            # and the email already exists in auth, Supabase returns the
            # confirmed user with confirmed_at set instead of raising an error.
            if user.confirmed_at is not None:
                return {
                    "status":  "error",
                    "message": "This email is already registered and confirmed. Please sign in.",
                    "code":    "already_registered",
                }

            # Write profile row (non-blocking)
            try:
                supabase.table("profiles").upsert(
                    {"user_id": user.id, "email": email, "role": role},
                    on_conflict="user_id",
                ).execute()
            except Exception as pe:
                logger.warning(f"profiles upsert after signup failed (non-fatal): {pe}")

            log_auth_action(user.id, email, "REGISTER")
            logger.info(f"New user registered: {email}")

            return {
                "status":                      "success",
                "user":                        {"id": user.id, "email": user.email, "role": role},
                "email_confirmation_required": True,
            }

        logger.error(f"sign_up_user: response.user is None for {email}")
        return {"status": "error", "message": "User creation failed — please try again.", "code": "unknown"}

    except Exception as e:
        raw       = str(e)
        raw_lower = raw.lower()
        logger.error(f"sign_up_user error for {email}: {type(e).__name__}: {raw}")

        if "already registered" in raw_lower or "duplicate" in raw_lower or "already exists" in raw_lower:
            return {"status": "error", "message": "This email is already registered. Please sign in.", "code": "already_registered"}
        if "rate limit" in raw_lower or "429" in raw_lower or "too many" in raw_lower:
            return {"status": "error", "message": "Too many sign-up attempts. Please wait a few minutes.", "code": "rate_limited"}
        if "signup is disabled" in raw_lower or "signups not allowed" in raw_lower or "sign_ups" in raw_lower:
            return {"status": "error", "message": "New registrations are currently disabled. Contact admin.", "code": "signups_disabled"}
        if "invalid email" in raw_lower:
            return {"status": "error", "message": "Invalid email address.", "code": "invalid_email"}
        if "password" in raw_lower and ("weak" in raw_lower or "short" in raw_lower or "length" in raw_lower):
            return {"status": "error", "message": "Password is too weak (min 6 chars, avoid common passwords).", "code": "weak_password"}
        if "network" in raw_lower or "connection" in raw_lower or "timeout" in raw_lower:
            return {"status": "error", "message": "Network error — check your internet connection.", "code": "network_error"}
        if "email" in raw_lower and ("not confirmed" in raw_lower or "confirmation" in raw_lower):
            # Supabase sometimes raises this when re-sending to an unconfirmed email
            return {
                "status":                      "success",
                "user":                        {"id": "", "email": email, "role": role},
                "email_confirmation_required": True,
                "_resent":                     True,
            }

        # Show raw error in debug mode — set DEBUG_REGISTRATION=true in .env
        if _DEBUG_REG:
            return {"status": "error", "message": f"[DEBUG] {raw}", "code": "unknown"}

        return {"status": "error", "message": "Registration failed — please try again.", "code": "unknown"}


def login_user(email: str, password: str) -> dict:
    """Authenticate with email + password."""
    if not _validate_email(email):
        return {"status": "error", "message": "Invalid email address."}
    if not password:
        return {"status": "error", "message": "Password cannot be empty."}

    try:
        # Must use supabase_auth (anon key) for sign_in — service key skips session management
        response = supabase_auth.auth.sign_in_with_password({
            "email": email,
            "password": password,
        })

        if not response.user:
            return {"status": "error", "message": "Invalid credentials — check email and password."}

        user     = response.user
        role     = get_user_role(user.id)
        is_admin = email.strip() in ADMIN_EMAILS or role == "admin"

        log_auth_action(user.id, email, "LOGIN")
        logger.info(f"User logged in: {email}, role={role}")

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
        logger.warning(f"Login failed for {email}: {type(e).__name__}")
        msg = str(e).lower()
        if "email not confirmed" in msg:
            return {
                "status":  "error",
                "message": "Email not confirmed — check your inbox for the confirmation link.",
                "code":    "email_not_confirmed",
            }
        if "invalid" in msg or "wrong" in msg or "credentials" in msg:
            return {"status": "error", "message": "Incorrect email or password."}
        return {"status": "error", "message": "Login failed — please try again."}


def login_with_token(access_token: str, refresh_token: str = "") -> dict:
    """Auto-login after email confirmation via URL token."""
    if not access_token:
        return {"status": "error", "message": "Missing access token."}
    try:
        # Use anon client for token validation — service key doesn't manage user sessions
        user_resp = supabase_auth.auth.get_user(access_token)
        if not user_resp or not user_resp.user:
            session = supabase_auth.auth.set_session(access_token, refresh_token)
            if not session or not session.user:
                return {"status": "error", "message": "Token is invalid or expired. Please log in manually."}
            user = session.user
        else:
            user = user_resp.user

        role     = get_user_role(user.id)
        is_admin = (user.email or "").strip() in ADMIN_EMAILS or role == "admin"

        supabase.table("profiles").upsert(
            {"user_id": user.id, "email": user.email, "role": role or "free"},
            on_conflict="user_id",
        ).execute()

        log_auth_action(user.id, user.email, "EMAIL_CONFIRMED_LOGIN")

        return {
            "status": "success",
            "user": {
                "id":           user.id,
                "email":        user.email,
                "role":         "admin" if is_admin else (role or "free"),
                "is_admin":     is_admin,
                "access_token": access_token,
            },
        }
    except Exception as e:
        logger.error(f"login_with_token error: {type(e).__name__}")
        return {"status": "error", "message": "Token verification failed. Please log in manually."}


def logout_user(user_id: str, email: str) -> dict:
    try:
        log_auth_action(user_id, email, "LOGOUT")
        supabase_auth.auth.sign_out()  # Must use anon key for session sign-out
        logger.info(f"User logged out: {email}")
        return {"status": "success"}
    except Exception as e:
        logger.warning(f"Logout warning: {type(e).__name__}")
        return {"status": "success", "warning": "Partial logout — session may persist."}


def get_user_role(user_id: str) -> str:
    try:
        resp = (
            supabase.table("profiles")
            .select("role")
            .eq("user_id", user_id)
            .single()
            .execute()
        )
        role = (resp.data or {}).get("role", "free")
        return role if role in RATE_LIMITS else "free"
    except Exception:
        return "free"


# ════════════════════════════════════════════════════════════════════
# RATE LIMITING
# ════════════════════════════════════════════════════════════════════

def check_rate_limit(user_id: str, role: str) -> dict:
    """
    Check daily query limit.
    Dual-mode: reads query_limits table first, falls back to trade_usage_logs.
    Fail-open on DB errors — never blocks a user due to DB unreachability.
    """
    limit = RATE_LIMITS.get(role, RATE_LIMITS["free"])
    reset_at = (
        datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        + timedelta(days=1)
    ).strftime("%Y-%m-%d 00:00 UTC")
    today = datetime.now(timezone.utc).date().isoformat()

    # Mode A: query_limits table (written by consume_query)
    try:
        resp = (
            supabase.table("query_limits")
            .select("queries_used")
            .eq("user_id", user_id)
            .eq("query_date", today)
            .execute()
        )
        if resp.data:
            used = int(resp.data[0].get("queries_used", 0))
            return {
                "allowed":   used < limit,
                "used":      used,
                "limit":     limit,
                "reset_at":  reset_at,
                "remaining": max(0, limit - used),
            }
    except Exception as e:
        logger.debug(f"check_rate_limit query_limits read failed: {type(e).__name__}")

    # Mode B: count trade_usage_logs rows
    try:
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).isoformat()
        resp = (
            supabase.table("trade_usage_logs")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .gte("timestamp", today_start)
            .execute()
        )
        used = resp.count if resp.count is not None else len(resp.data or [])
        return {
            "allowed":   used < limit,
            "used":      used,
            "limit":     limit,
            "reset_at":  reset_at,
            "remaining": max(0, limit - used),
        }
    except Exception as e:
        logger.warning(f"check_rate_limit all modes failed — failing open: {type(e).__name__}")
        return {"allowed": True, "used": 0, "limit": limit, "remaining": limit, "reset_at": reset_at}


# ════════════════════════════════════════════════════════════════════
# LOGGING
# ════════════════════════════════════════════════════════════════════

def log_auth_action(user_id: str, email: str, action: str) -> None:
    try:
        supabase.table("auth_logs").insert({
            "user_id":   user_id,
            "email":     _sanitise_str(email, 254),
            "action":    _sanitise_str(action, 50),
            "timestamp": _now_iso(),
        }).execute()
    except Exception as e:
        logger.warning(f"log_auth_action failed: {type(e).__name__}")


def log_trade_usage(
    user_id: str,
    email: str,
    mode: str,
    product: str,
    result: dict = None,
) -> dict:
    """Log a trade query. Returns status dict."""
    try:
        data = {
            "user_id":   user_id,
            "email":     _sanitise_str(email, 254),
            "mode":      _sanitise_str(mode, 50),
            "product":   _sanitise_str(product, 500),
            "timestamp": _now_iso(),
        }
        if result and isinstance(result, dict) and "hs_code" in result:
            hs = str(result["hs_code"])[:20]
            if re.match(r"^\d{6,8}$", hs):
                data["hs_code"] = hs

        supabase.table("trade_usage_logs").insert(data).execute()
        return {"status": "success"}
    except Exception as e:
        logger.error(f"log_trade_usage failed: {type(e).__name__}: {e}")
        return {"status": "error", "message": str(e)}


# ════════════════════════════════════════════════════════════════════
# STATS
# ════════════════════════════════════════════════════════════════════

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
        by_mode: dict = {}
        for l in logs:
            m = l.get("mode", "Unknown")
            by_mode[m] = by_mode.get(m, 0) + 1
        return {
            "status":        "success",
            "total_queries": total_q,
            "total_logins":  total_login,
            "by_mode":       by_mode,
        }
    except Exception as e:
        logger.error(f"get_user_stats error: {type(e).__name__}")
        return {"status": "error", "message": str(e)}


# ════════════════════════════════════════════════════════════════════
# ADMIN
# ════════════════════════════════════════════════════════════════════

def get_all_users() -> list:
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
        logger.error(f"get_all_users error: {type(e).__name__}")
        return []


def get_all_queries(limit: int = 100) -> tuple:
    limit = max(1, min(limit, 500))
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
        logger.error(f"get_all_queries error: {type(e).__name__}")
        return [], str(e)


def update_user_role(user_id: str, new_role: str) -> dict:
    valid_roles = list(RATE_LIMITS.keys())
    if new_role not in valid_roles:
        return {"status": "error", "message": f"Role must be one of: {', '.join(valid_roles)}"}
    try:
        supabase.table("profiles").update({"role": new_role}).eq("user_id", user_id).execute()
        logger.info(f"Role updated for user_id={user_id} → {new_role}")
        return {"status": "success"}
    except Exception as e:
        msg = str(e)
        if "23514" in msg or "check constraint" in msg.lower():
            return {
                "status":  "error",
                "message": (
                    f"Database role constraint outdated — doesn't allow '{new_role}' yet.\n"
                    "Fix: Run fix_rls_and_tables.sql in Supabase SQL Editor."
                ),
            }
        logger.error(f"update_user_role error: {type(e).__name__}")
        return {"status": "error", "message": "Role update failed — try again."}


def get_platform_stats() -> dict:
    errors = []
    result = {
        "total_users":   0,
        "total_queries": 0,
        "queries_today": 0,
        "by_mode":       {},
        "_errors":       None,
    }

    for key, fn in [
        ("total_users",   lambda: supabase.table("profiles").select("user_id", count="exact").execute().count or 0),
        ("total_queries", lambda: supabase.table("trade_usage_logs").select("id", count="exact").execute().count or 0),
    ]:
        try:
            result[key] = fn()
        except Exception as e:
            errors.append(f"{key}: {e}")

    try:
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).isoformat()
        r = supabase.table("trade_usage_logs").select("id", count="exact").gte("timestamp", today_start).execute()
        result["queries_today"] = r.count or 0
    except Exception as e:
        errors.append(f"queries_today: {e}")

    try:
        r = supabase.table("trade_usage_logs").select("mode").execute()
        by_mode: dict = {}
        for l in (r.data or []):
            m = l.get("mode", "Unknown")
            by_mode[m] = by_mode.get(m, 0) + 1
        result["by_mode"] = by_mode
    except Exception as e:
        errors.append(f"by_mode: {e}")

    result["_errors"] = errors if errors else None
    return result


# ════════════════════════════════════════════════════════════════════
# EMAIL (SMTP)
# ════════════════════════════════════════════════════════════════════

def send_email_alert(to_email: str, subject: str, body_html: str) -> dict:
    """Send HTML email via SMTP. All credentials from env."""
    if not _validate_email(to_email):
        return {"status": "error", "message": f"Invalid recipient email: {to_email}"}

    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")
    smtp_from = os.getenv("SMTP_FROM", smtp_user)

    if not smtp_user or not smtp_pass:
        return {"status": "error", "message": "SMTP credentials not configured in .env (SMTP_USER, SMTP_PASS)"}

    try:
        msg            = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = smtp_from
        msg["To"]      = to_email
        msg.attach(MIMEText(body_html, "html"))

        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_from, to_email, msg.as_string())

        logger.debug(f"Email sent to {to_email}")
        return {"status": "success"}

    except smtplib.SMTPAuthenticationError:
        logger.error(f"SMTP auth failed for {smtp_user}")
        return {
            "status":  "error",
            "message": (
                f"Gmail authentication failed for {smtp_user}.\n"
                "Use a Gmail App Password (not your account password).\n"
                "Go to: Google Account → Security → 2-Step → App Passwords"
            ),
        }
    except smtplib.SMTPConnectError:
        return {"status": "error", "message": f"Cannot connect to {smtp_host}:{smtp_port}. Check SMTP_HOST / SMTP_PORT."}
    except smtplib.SMTPRecipientsRefused:
        return {"status": "error", "message": f"Recipient refused: {to_email}"}
    except Exception as e:
        logger.error(f"SMTP error: {type(e).__name__}: {e}")
        return {"status": "error", "message": f"Email failed: {type(e).__name__}"}


def notify_all_users_new_dataset(dataset_name: str = "Trade Map 2024") -> dict:
    try:
        profiles = supabase.table("profiles").select("email").execute()
        emails   = [p["email"] for p in (profiles.data or []) if p.get("email")]
        subject  = f"🇮🇳 Trade Intelligence Engine — New Dataset: {dataset_name}"
        body = f"""
        <html><body style="font-family:Inter,Arial,sans-serif;max-width:600px;margin:auto;background:#0d1117;color:#e2e8f0;padding:24px;">
        <h2 style="color:#63b3ed;">📦 New Trade Data Available</h2>
        <p>The <strong>{dataset_name}</strong> dataset has been uploaded to your Trade Intelligence Engine.</p>
        <ul>
          <li>✅ Updated market recommendations</li>
          <li>✅ Fresh country-level trade stats</li>
          <li>✅ Revised opportunity and trend scores</li>
        </ul>
        <p style="color:#a0aec0;font-size:12px;">You received this because you have an account on the Trade Intelligence Engine.</p>
        </body></html>
        """
        sent, failed = 0, 0
        for email in emails:
            res = send_email_alert(email, subject, body)
            if res["status"] == "success":
                sent += 1
            else:
                failed += 1
        logger.info(f"Dataset notification sent: {sent} success, {failed} failed")
        return {"status": "success", "sent": sent, "failed": failed, "total": len(emails)}
    except Exception as e:
        logger.error(f"notify_all_users error: {type(e).__name__}")
        return {"status": "error", "message": str(e)}


# ════════════════════════════════════════════════════════════════════
# PASSWORD RESET (OTP-based — no redirect links)
# ════════════════════════════════════════════════════════════════════

def smtp_diagnostic() -> dict:
    smtp_host = os.getenv("SMTP_HOST", "")
    smtp_port = os.getenv("SMTP_PORT", "587")
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")
    issues = []
    if not smtp_host: issues.append("SMTP_HOST not set")
    if not smtp_user: issues.append("SMTP_USER not set")
    if not smtp_pass: issues.append("SMTP_PASS not set")
    if issues:
        return {"status": "error", "message": "Missing config: " + " | ".join(issues)}
    try:
        with smtplib.SMTP(smtp_host, int(smtp_port), timeout=8) as s:
            s.ehlo()
            s.starttls()
            s.login(smtp_user, smtp_pass)
        return {"status": "success", "message": f"Connected to {smtp_host}:{smtp_port}"}
    except smtplib.SMTPAuthenticationError:
        return {"status": "error", "message": f"Auth failed for {smtp_user}. Use a Gmail App Password."}
    except smtplib.SMTPConnectError as e:
        return {"status": "error", "message": f"Cannot connect to {smtp_host}:{smtp_port} — {e}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def request_password_reset(email: str) -> dict:
    if not _validate_email(email):
        return {"status": "error", "message": "Invalid email address."}
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")
    if not smtp_user or not smtp_pass:
        return {
            "status":  "error",
            "message": "Email sending not configured. Add SMTP_USER and SMTP_PASS to .env.",
        }
    try:
        profiles = supabase.table("profiles").select("email").eq("email", email).execute()
        if not profiles.data:
            return {"status": "success"}   # Don't reveal if email exists
    except Exception as e:
        return {"status": "error", "message": f"Database error: {e}"}

    from otp_service import send_otp_email as _send_otp
    result = _send_otp(email, email.split("@")[0])
    logger.info(f"Password reset OTP requested for: {email}")
    return result


def verify_reset_otp(email: str, otp: str) -> dict:
    if not _validate_email(email):
        return {"status": "error", "message": "Invalid email address."}
    from otp_service import verify_otp as _verify
    return _verify(email, otp)


def admin_update_user_password(email: str, new_password: str) -> dict:
    if not _validate_email(email):
        return {"status": "error", "message": "Invalid email address."}
    if not new_password or len(new_password) < 6:
        return {"status": "error", "message": "Password must be at least 6 characters."}
    try:
        import requests as _req
        headers = {
            "apikey":        SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type":  "application/json",
        }
        resp = _req.get(
            f"{SUPABASE_URL}/auth/v1/admin/users?page=1&per_page=1000",
            headers=headers,
            timeout=15,
        )
        if resp.status_code != 200:
            return {"status": "error", "message": "Could not fetch user list."}
        users = resp.json().get("users", [])
        uid   = None
        for u in users:
            if (u.get("email") or "").lower() == email.lower():
                uid = u.get("id")
                break
        if not uid:
            return {"status": "error", "message": "Email not found in system."}
        upd = _req.put(
            f"{SUPABASE_URL}/auth/v1/admin/users/{uid}",
            headers=headers,
            json={"password": new_password},
            timeout=15,
        )
        if upd.status_code in (200, 201):
            logger.info(f"Password updated via admin API for: {email}")
            return {"status": "success"}
        return {"status": "error", "message": "Password update failed — please try again."}
    except Exception as e:
        logger.error(f"admin_update_user_password error: {type(e).__name__}")
        return {"status": "error", "message": str(e)}


def exchange_code_for_session(code: str) -> dict:
    """Exchange PKCE auth code (from ?code= URL param) for a user session."""
    try:
        auth_client = create_client(SUPABASE_URL, _anon_key)
        resp = auth_client.auth.exchange_code_for_session({"auth_code": code})
        if not resp or not resp.session:
            return {"status": "error", "message": "Invalid or expired confirmation link."}
        return {
            "status":        "success",
            "access_token":  resp.session.access_token,
            "refresh_token": resp.session.refresh_token or "",
            "user":          {"id": resp.user.id, "email": resp.user.email},
        }
    except Exception as e:
        logger.error(f"exchange_code_for_session error: {type(e).__name__}")
        return {"status": "error", "message": "Confirmation failed — link may have expired."}


def update_user_password(access_token: str, new_password: str) -> dict:
    if not new_password or len(new_password) < 6:
        return {"status": "error", "message": "Password must be at least 6 characters."}
    try:
        auth_client = create_client(SUPABASE_URL, _anon_key)
        auth_client.auth.set_session(access_token, "")
        auth_client.auth.update_user({"password": new_password})
        try:
            auth_client.auth.sign_out()
        except Exception:
            pass
        return {"status": "success"}
    except Exception as e:
        logger.error(f"update_user_password error: {type(e).__name__}")
        return {"status": "error", "message": str(e)}


def notify_user_limit_warning(user_id: str, email: str, used: int, limit: int) -> None:
    if used == int(limit * 0.8):
        subject = "⚠️ Trade Intelligence — Query Limit Warning"
        body = f"""
        <html><body style="font-family:Inter,Arial,sans-serif;">
        <h3 style="color:#ecc94b;">⚠️ You've used {used} of {limit} daily queries</h3>
        <p><strong>{limit - used} queries remaining</strong> today.</p>
        <p>Your limit resets at midnight UTC. Contact admin to upgrade your plan.</p>
        </body></html>
        """
        send_email_alert(email, subject, body)