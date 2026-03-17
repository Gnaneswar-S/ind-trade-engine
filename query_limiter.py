"""
query_limiter.py
════════════════════════════════════════════════════════════════════
Production-grade query limit system — Trade Intelligence Engine v3.5

DUAL-MODE OPERATION:
  Mode A (after sql_schema_v3.sql is run):
    → Uses consume_query / get_query_status Postgres RPCs
    → Atomic, race-condition-free, server-enforced

  Mode B (IMMEDIATE fallback — works RIGHT NOW without any SQL):
    → Falls back to counting trade_usage_logs rows for display
    → Falls back to incrementing a Supabase row for enforcement
    → No RPC required. Works the same day you update the code.

The system auto-detects which mode is available on every call.
Once you run sql_schema_v3.sql it silently upgrades to Mode A.

WHY THE BUG WAS STILL SHOWING 10/10:
  1. sql_schema_v3.sql not run → get_query_status RPC doesn't exist
  2. RPC throws exception → fallback returns {"remaining": 10} always
  3. Cache is NEVER cleared properly because st.cache_data.clear()
     only works when called on the decorated function object directly
     — calling it inside consume_query after an exception skips it
  4. Result: display always shows full quota regardless of queries used
════════════════════════════════════════════════════════════════════
"""

import os
import logging
import streamlit as st
from datetime import datetime, date, timezone, timedelta

logger = logging.getLogger("query_limiter")

ROLE_DAILY_LIMITS: dict[str, int] = {
    "free": 10, "user": 50, "analyst": 150, "pro": 500, "admin": 999999
}

ROLE_LABELS: dict[str, str] = {
    "free":    "Free (10/day)",
    "user":    "Standard (50/day)",
    "analyst": "Analyst (150/day)",
    "pro":     "Pro (500/day)",
    "admin":   "Admin (Unlimited)",
}

# Session state key where we store live count (updated after every consume)
_SS_KEY = "_ql_live"   # {"used": N, "limit": N, "reset_date": "YYYY-MM-DD"}


# ════════════════════════════════════════════════════════════════════
# INTERNAL: DB helpers
# ════════════════════════════════════════════════════════════════════

def _get_supabase():
    from supabase_service import supabase
    return supabase


def _today_utc() -> str:
    return date.today().strftime("%Y-%m-%d")


def _reset_at_utc() -> str:
    """ISO string for midnight UTC tomorrow."""
    tomorrow = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ) + timedelta(days=1)
    return tomorrow.isoformat()


def _get_role(user_id: str) -> str:
    try:
        sb = _get_supabase()
        r = sb.table("profiles").select("role").eq("user_id", user_id).single().execute()
        return (r.data or {}).get("role", "free")
    except Exception:
        return "free"


def _count_today_from_logs(user_id: str) -> int:
    """
    Fallback: count today's queries.
    Priority:
      1. query_limits table row (written by Mode B consume_query)
      2. trade_usage_logs row count (last resort)
    Both use UTC date so count persists correctly across re-logins.
    """
    today = _today_utc()
    # 1. Try query_limits table first (consistent with Mode B consume_query)
    try:
        sb = _get_supabase()
        resp = (
            sb.table("query_limits")
            .select("queries_used")
            .eq("user_id", user_id)
            .eq("query_date", today)
            .execute()
        )
        if resp.data:
            return int(resp.data[0].get("queries_used", 0))
    except Exception as e:
        logger.debug(f"query_limits read failed (may not exist yet): {e}")

    # 2. Fallback: count trade_usage_logs rows for today
    try:
        sb = _get_supabase()
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).isoformat()
        resp = (
            sb.table("trade_usage_logs")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .gte("timestamp", today_start)
            .execute()
        )
        return resp.count if resp.count is not None else len(resp.data or [])
    except Exception as e:
        logger.warning(f"_count_today_from_logs fallback failed: {e}")
        return 0


def _rpc_available(rpc_name: str, user_id: str) -> bool:
    """Quick probe to see if an RPC function exists in this Supabase project."""
    try:
        sb = _get_supabase()
        sb.rpc(rpc_name, {"p_user_id": user_id}).execute()
        return True
    except Exception as e:
        msg = str(e).lower()
        # "function not found" / "does not exist" means SQL not run yet
        if "not exist" in msg or "not found" in msg or "404" in msg or "42883" in msg:
            return False
        return True   # Other errors (network) — assume it exists, fail gracefully


# ════════════════════════════════════════════════════════════════════
# SESSION STATE CACHE (lives in Streamlit memory, per-user per-session)
# This is cleared after every consume and after every page rerun.
# It is the fast-path: no DB hit on every render.
# ════════════════════════════════════════════════════════════════════

def _ss_get(user_id: str) -> dict | None:
    """Get session state live info. Returns None if missing or stale date."""
    info = st.session_state.get(_SS_KEY)
    if not info or info.get("user_id") != user_id:
        return None
    if info.get("reset_date") != _today_utc():
        return None   # New day — stale
    return info


def _ss_set(user_id: str, used: int, limit: int) -> None:
    st.session_state[_SS_KEY] = {
        "user_id":    user_id,
        "used":       used,
        "limit":      limit,
        "reset_date": _today_utc(),
        "reset_at":   _reset_at_utc(),
    }


def _ss_clear() -> None:
    st.session_state.pop(_SS_KEY, None)


# ════════════════════════════════════════════════════════════════════
# PUBLIC: get_limit_status — always returns fresh-enough data
# ════════════════════════════════════════════════════════════════════

def get_limit_status(user_id: str) -> dict:
    """
    Returns current usage status for display.

    Priority:
      1. Session state live cache (updated by consume_query — no DB hit)
      2. Postgres RPC get_query_status (if SQL schema was run)
      3. Count trade_usage_logs rows (fallback, always works)
    """
    role  = st.session_state.get("user", {}).get("role", "free") or "free"
    limit = ROLE_DAILY_LIMITS.get(role, 10)

    # 1. Fast path: session state (set by consume_query)
    cached = _ss_get(user_id)
    if cached:
        used = cached["used"]
        lim  = cached.get("limit", limit)
        return {
            "status":       "limit_reached" if used >= lim else "ok",
            "queries_today": used,
            "daily_limit":   lim,
            "remaining":     max(0, lim - used),
            "reset_at":      cached.get("reset_at", _reset_at_utc()),
        }

    # 2. Try Postgres RPC (Mode A — after SQL schema is run)
    try:
        sb = _get_supabase()
        resp = sb.rpc("get_query_status", {"p_user_id": user_id}).execute()
        data = resp.data
        if isinstance(data, dict) and "queries_today" in data:
            used = data.get("queries_today", 0)
            lim  = data.get("daily_limit", limit)
            _ss_set(user_id, used, lim)
            return data
    except Exception as e:
        msg = str(e).lower()
        if "not exist" not in msg and "not found" not in msg and "42883" not in msg:
            logger.warning(f"get_query_status RPC error (non-missing): {e}")
        # Fall through to Mode B

    # 3. Fallback: count logs (Mode B — works immediately, no SQL needed)
    used  = _count_today_from_logs(user_id)
    _ss_set(user_id, used, limit)
    return {
        "status":        "limit_reached" if used >= limit else "ok",
        "queries_today":  used,
        "daily_limit":    limit,
        "remaining":      max(0, limit - used),
        "reset_at":       _reset_at_utc(),
    }


# ════════════════════════════════════════════════════════════════════
# PUBLIC: consume_query — call AFTER every successful AI response
# ════════════════════════════════════════════════════════════════════

def consume_query(user_id: str) -> dict:
    """
    Record that one query was used. Clears session state cache so
    the very next render shows the updated count.

    Mode A: calls consume_query Postgres RPC (atomic, server-side)
    Mode B: inserts a row into query_limits table directly (fallback)
            If neither works, still clears cache so log-row count works.

    ALWAYS call this after a successful AI response.
    """
    _ss_clear()   # Always clear first so next get_limit_status re-reads DB

    # Mode A: Postgres RPC
    try:
        sb = _get_supabase()
        resp = sb.rpc("consume_query", {"p_user_id": user_id}).execute()
        data = resp.data
        if isinstance(data, dict) and data.get("status") in ("ok", "limit_reached"):
            used = data.get("queries_today", 0)
            lim  = data.get("daily_limit", ROLE_DAILY_LIMITS.get("free", 10))
            _ss_set(user_id, used, lim)
            logger.info(f"consume_query RPC: uid={user_id[:8]}… {used}/{lim}")
            return data
    except Exception as e:
        msg = str(e).lower()
        rpc_missing = "not exist" in msg or "not found" in msg or "42883" in msg
        if not rpc_missing:
            logger.error(f"consume_query RPC error: {e}")
        # Fall through to Mode B

    # Mode B: direct upsert into query_limits (if table exists but not the function)
    try:
        sb = _get_supabase()
        role  = _get_role(user_id)
        limit = ROLE_DAILY_LIMITS.get(role, 10)
        today = _today_utc()

        # Try to upsert — increment counter
        existing = (
            sb.table("query_limits")
            .select("queries_used")
            .eq("user_id", user_id)
            .eq("query_date", today)
            .execute()
        )
        if existing.data:
            used = existing.data[0]["queries_used"] + 1
            sb.table("query_limits").update({
                "queries_used": used,
                "last_query_at": datetime.now(timezone.utc).isoformat(),
            }).eq("user_id", user_id).eq("query_date", today).execute()
        else:
            used = 1
            sb.table("query_limits").insert({
                "user_id":       user_id,
                "query_date":    today,
                "queries_used":  1,
                "daily_limit":   limit,
                "last_query_at": datetime.now(timezone.utc).isoformat(),
            }).execute()

        _ss_set(user_id, used, limit)
        logger.info(f"consume_query direct: uid={user_id[:8]}… {used}/{limit}")
        return {"status": "ok", "queries_today": used, "daily_limit": limit,
                "remaining": max(0, limit - used), "reset_at": _reset_at_utc()}

    except Exception as e:
        logger.warning(f"consume_query direct fallback failed: {e}")

    # Mode C: Session-only increment (at least the display updates this session)
    cached = _ss_get(user_id) or {}
    role   = st.session_state.get("user", {}).get("role", "free") or "free"
    limit  = ROLE_DAILY_LIMITS.get(role, 10)
    used   = cached.get("used", _count_today_from_logs(user_id)) + 1
    _ss_set(user_id, used, limit)
    logger.warning(f"consume_query session-only: uid={user_id[:8]}… {used}/{limit}")
    return {"status": "ok", "queries_today": used, "daily_limit": limit,
            "remaining": max(0, limit - used), "reset_at": _reset_at_utc(),
            "_session_only": True}


# ════════════════════════════════════════════════════════════════════
# PUBLIC: rate_guard — call at top of every AI page
# ════════════════════════════════════════════════════════════════════

def rate_guard(user: dict) -> bool:
    """
    Gate for AI pages. Returns True = proceed, False = blocked.

    Shows "X of Y remaining" display above the form.
    After the AI call succeeds, consume_query(user_id) MUST be called.
    """
    user_id = user.get("id", "")
    role    = user.get("role", "free")

    info      = get_limit_status(user_id)
    remaining = info.get("remaining", 1)
    limit     = info.get("daily_limit", ROLE_DAILY_LIMITS.get(role, 10))
    reset_at  = info.get("reset_at", _reset_at_utc())

    # Update session_state for sidebar display
    st.session_state.rate_info = info

    if info.get("status") == "limit_reached" or remaining <= 0:
        st.error(
            f"🚫 **Daily query limit reached** "
            f"({limit} queries for **{ROLE_LABELS.get(role, role.upper())}** plan).\n\n"
            f"⏰ Resets in **{_format_reset(reset_at)}**. Contact admin to upgrade."
        )
        if role in ("free", "user"):
            st.info("💡 **Upgrade to Analyst or Pro** for 150–500 daily queries.")
        return False

    used  = info.get("queries_today", 0)
    color = "#48bb78" if remaining > limit * 0.4 else ("#ecc94b" if remaining > 2 else "#fc8181")
    st.markdown(
        f'<div style="font-size:0.75rem;color:{color};text-align:right;margin-bottom:6px;">'
        f'⚡ {remaining} of {limit} queries remaining today '
        f'<span style="color:#4a5568;">({used} used)</span></div>',
        unsafe_allow_html=True
    )
    return True


# ════════════════════════════════════════════════════════════════════
# PUBLIC: render_rate_bar — sidebar progress bar
# ════════════════════════════════════════════════════════════════════

def render_rate_bar(user_id: str, role: str) -> dict:
    """Renders the compact sidebar rate bar. Call once per sidebar render."""
    info  = get_limit_status(user_id)
    used  = info.get("queries_today", 0)
    limit = info.get("daily_limit", ROLE_DAILY_LIMITS.get(role, 10))
    pct   = used / max(limit, 1)
    color = "#48bb78" if pct < 0.6 else ("#ecc94b" if pct < 0.85 else "#fc8181")
    reset = _format_reset(info.get("reset_at", ""))

    st.markdown(f"""
    <div style="padding:0 8px 8px;">
      <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
        <span style="color:#4a5568;font-size:0.68rem;">Daily Queries</span>
        <span style="color:{color};font-size:0.68rem;font-weight:600;">{used}/{limit}</span>
      </div>
      <div style="background:#0a0f1e;border-radius:3px;height:4px;">
        <div style="width:{min(pct*100,100):.0f}%;height:4px;border-radius:3px;
                    background:{color};transition:width 0.3s;"></div>
      </div>
      <div style="color:#4a5568;font-size:0.65rem;margin-top:2px;">Resets in {reset}</div>
    </div>
    """, unsafe_allow_html=True)
    return info


# ════════════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════════════

def _format_reset(reset_at) -> str:
    if not reset_at or str(reset_at) in ("unknown", ""):
        return "midnight UTC"
    try:
        if isinstance(reset_at, str):
            dt = datetime.fromisoformat(reset_at.replace("Z", "+00:00"))
        else:
            dt = reset_at
        diff = dt - datetime.now(timezone.utc)
        total = max(0, int(diff.total_seconds()))
        h, m  = divmod(total, 3600)
        m     = m // 60
        return f"{h}h {m}m" if h > 0 else f"{m}m"
    except Exception:
        return str(reset_at)[:16]