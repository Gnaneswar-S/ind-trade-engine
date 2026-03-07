"""
otp_service.py
──────────────────────────────────────────────────────────────
Two-Factor Authentication via Email OTP.
Architecture:
  • Stateless — OTP state lives in Supabase `otp_store` table
  • SHA-256 hashed storage — plaintext OTP is never persisted
  • 5-minute TTL enforced at read time (not just write time)
  • One active OTP per email — upsert prevents duplicate rows
  • Secure random via secrets module (not random/randint)

Required Supabase table:
  CREATE TABLE otp_store (
      email       TEXT PRIMARY KEY,
      otp_hash    TEXT NOT NULL,
      expires_at  TIMESTAMPTZ NOT NULL,
      used        BOOLEAN DEFAULT FALSE,
      created_at  TIMESTAMPTZ DEFAULT NOW()
  );
  GRANT ALL ON otp_store TO service_role;
──────────────────────────────────────────────────────────────
"""

import os
import secrets
import hashlib
from datetime import datetime, timedelta, timezone

from supabase import create_client, Client
from dotenv import load_dotenv

# Import SMTP helper from supabase_service to avoid duplicating SMTP config
from supabase_service import send_email_alert

load_dotenv()

_SUPABASE_URL = os.getenv("SUPABASE_URL")
_SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

if not _SUPABASE_URL or not _SUPABASE_KEY:
    raise ValueError("❌ otp_service: SUPABASE_URL / SUPABASE_SERVICE_KEY missing in .env")

_supabase: Client = create_client(_SUPABASE_URL, _SUPABASE_KEY)

OTP_LENGTH      = 6
OTP_TTL_MINUTES = 5
APP_NAME        = "🇮🇳 Trade Intelligence Engine"


# ──────────────────────────────────────────────
# INTERNAL HELPERS
# ──────────────────────────────────────────────

def _hash(otp: str) -> str:
    """SHA-256 hash — never store a plaintext OTP."""
    return hashlib.sha256(otp.encode("utf-8")).hexdigest()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _expiry() -> str:
    return (_now_utc() + timedelta(minutes=OTP_TTL_MINUTES)).isoformat()


# ──────────────────────────────────────────────
# PUBLIC API
# ──────────────────────────────────────────────

def generate_otp() -> str:
    """
    Generate a cryptographically secure 6-digit OTP.
    Uses secrets.randbelow(10) — NOT random.randint.
    Returns a zero-padded string, e.g. '042831'.
    """
    return "".join(str(secrets.randbelow(10)) for _ in range(OTP_LENGTH))


def send_otp_email(email: str, display_name: str = "") -> dict:
    """
    1. Generate OTP
    2. Store SHA-256 hash in Supabase otp_store (upsert)
    3. Send HTML email with the plaintext OTP
    Returns {"status": "success"} or {"status": "error", "message": "..."}
    """
    otp        = generate_otp()
    otp_hash   = _hash(otp)
    expires_at = _expiry()
    name       = display_name.strip() or email.split("@")[0]

    # ── Persist (upsert = one OTP per email at a time) ──
    try:
        _supabase.table("otp_store").upsert(
            {
                "email":      email,
                "otp_hash":   otp_hash,
                "expires_at": expires_at,
                "used":       False,
                "created_at": _now_utc().isoformat(),
            },
            on_conflict="email",
        ).execute()
    except Exception as exc:
        return {"status": "error", "message": f"OTP storage failed: {exc}"}

    # ── Email body ──
    body = f"""
    <html>
    <body style="margin:0;padding:0;background:#0d1117;font-family:'Inter',Arial,sans-serif;">
      <table width="100%" cellpadding="0" cellspacing="0"
             style="max-width:520px;margin:40px auto;background:#161b22;
                    border-radius:14px;border:1px solid #30363d;overflow:hidden;">

        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#1a3a5c,#1a6fa8);
                     padding:28px 32px;text-align:center;">
            <div style="font-size:2rem;">🔐</div>
            <h1 style="color:#ffffff;font-size:1.3rem;margin:8px 0 4px;">
              Two-Factor Verification
            </h1>
            <p style="color:#a8d4f5;font-size:0.85rem;margin:0;">
              {APP_NAME}
            </p>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="padding:32px;">
            <p style="color:#c9d1d9;font-size:0.95rem;margin:0 0 20px;">
              Hi <strong style="color:#e6edf3;">{name}</strong>,
            </p>
            <p style="color:#8b949e;font-size:0.9rem;margin:0 0 24px;">
              Use the following One-Time Password to complete your login.
              Do not share this code with anyone.
            </p>

            <!-- OTP Box -->
            <div style="text-align:center;margin:24px 0;">
              <span style="display:inline-block;background:#1f6feb;color:#ffffff;
                           font-size:2.6rem;font-weight:700;letter-spacing:14px;
                           padding:18px 36px;border-radius:12px;
                           font-family:'Courier New',monospace;">
                {otp}
              </span>
            </div>

            <!-- Expiry warning -->
            <div style="background:#2d1f0e;border:1px solid #d29922;border-radius:8px;
                        padding:12px 16px;margin:20px 0;text-align:center;">
              <span style="color:#d29922;font-size:0.85rem;font-weight:600;">
                ⏱ Expires in {OTP_TTL_MINUTES} minutes
              </span>
            </div>

            <p style="color:#6e7681;font-size:0.8rem;margin:0;">
              If you did not attempt to log in, please ignore this email.
              Your account remains secure.
            </p>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background:#0d1117;padding:16px 32px;text-align:center;
                     border-top:1px solid #30363d;">
            <p style="color:#484f58;font-size:0.75rem;margin:0;">
              {APP_NAME} · Do not reply to this email
            </p>
          </td>
        </tr>

      </table>
    </body>
    </html>
    """

    return send_email_alert(
        to_email=email,
        subject=f"🔐 Your Login OTP — {APP_NAME}",
        body_html=body,
    )


def verify_otp(email: str, otp_input: str) -> dict:
    """
    Verify submitted OTP against the stored hash.
    Enforces: correct length, not expired, not already used, correct hash.
    Marks OTP as used on success (one-time use).

    Returns {"status": "success"} or {"status": "error", "message": "..."}
    """
    otp_clean = (otp_input or "").strip()

    if len(otp_clean) != OTP_LENGTH or not otp_clean.isdigit():
        return {"status": "error",
                "message": f"OTP must be exactly {OTP_LENGTH} digits."}

    # ── Fetch stored record ──
    try:
        resp = (
            _supabase.table("otp_store")
            .select("otp_hash, expires_at, used")
            .eq("email", email)
            .single()
            .execute()
        )
        record = resp.data
    except Exception:
        return {"status": "error",
                "message": "No OTP found for this email. Please request a new one."}

    if not record:
        return {"status": "error",
                "message": "No OTP found. Please request a new one."}

    # ── Already used? ──
    if record.get("used"):
        return {"status": "error",
                "message": "This OTP has already been used. Please request a new one."}

    # ── Expired? ──
    try:
        expires_at = datetime.fromisoformat(
            record["expires_at"].replace("Z", "+00:00")
        )
        if _now_utc() > expires_at:
            return {"status": "error",
                    "message": f"OTP expired after {OTP_TTL_MINUTES} minutes. "
                               "Please request a new one."}
    except Exception:
        pass  # If we can't parse, proceed to hash check

    # ── Hash check ──
    if _hash(otp_clean) != record["otp_hash"]:
        return {"status": "error", "message": "Incorrect OTP. Please try again."}

    # ── Mark used ──
    try:
        _supabase.table("otp_store").update({"used": True}).eq("email", email).execute()
    except Exception:
        pass  # Non-fatal — OTP validated successfully

    return {"status": "success"}


def invalidate_otp(email: str) -> None:
    """Hard-delete any active OTP for an email (e.g. on logout or account deletion)."""
    try:
        _supabase.table("otp_store").delete().eq("email", email).execute()
    except Exception:
        pass