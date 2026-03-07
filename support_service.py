"""
support_service.py
──────────────────────────────────────────────────────────────
Support Ticket System for 🇮🇳 Indian Trade Intelligence Engine

Ticket types:
  • contact_support  — general help request
  • report_ai_error  — incorrect AI output report
  • feature_request  — new feature idea

Ticket lifecycle:
  open → in_review → resolved | closed

All tickets stored in Supabase `support_tickets` table.
Admin email notifications on every new ticket.
──────────────────────────────────────────────────────────────
"""

import os
from datetime import datetime, timezone
from supabase_service import supabase, send_email_alert

# ── Config ────────────────────────────────────────────────────
TICKET_TYPES = {
    "contact_support": "💬 Contact Support",
    "report_ai_error": "🐛 Report AI Error",
    "feature_request":  "💡 Feature Request",
}

STATUS_LABELS = {
    "open":      "🟡 Open",
    "in_review": "🔵 In Review",
    "resolved":  "🟢 Resolved",
    "closed":    "⚫ Closed",
}

PRIORITY_LABELS = {
    "low":    "🟢 Low",
    "medium": "🟡 Medium",
    "high":   "🔴 High",
}

_ADMIN_EMAIL = os.getenv("ADMIN_EMAIL") or os.getenv("SMTP_FROM") or os.getenv("SMTP_USER", "")


# ══════════════════════════════════════════════════════════════
# WRITE OPERATIONS
# ══════════════════════════════════════════════════════════════

def submit_ticket(
    user_id:     str,
    email:       str,
    ticket_type: str,          # "contact_support" | "report_ai_error" | "feature_request"
    subject:     str,
    description: str,
    priority:    str = "medium",
    extra_data=None,                  # optional dict (e.g. the AI output that was wrong)
) -> dict:
    """
    Create a new support ticket in Supabase.
    Sends an email notification to the admin.
    Returns {"status": "success", "ticket_id": N} or {"status": "error", "message": "..."}
    """
    subject   = subject.strip()[:200]
    desc      = description.strip()[:4000]

    if not subject:
        return {"status": "error", "message": "Subject cannot be empty."}
    if not desc:
        return {"status": "error", "message": "Description cannot be empty."}
    if ticket_type not in TICKET_TYPES:
        return {"status": "error", "message": f"Unknown ticket type: {ticket_type}"}
    if priority not in PRIORITY_LABELS:
        priority = "medium"

    # Step 1: Save to Supabase (must succeed)
    try:
        row = {
            "user_id":     user_id,
            "email":       email,
            "ticket_type": ticket_type,
            "subject":     subject,
            "description": desc,
            "priority":    priority,
            "status":      "open",
            "extra_data":  extra_data or {},
            "created_at":  datetime.now(timezone.utc).isoformat(),
            "updated_at":  datetime.now(timezone.utc).isoformat(),
        }
        resp = supabase.table("support_tickets").insert(row).execute()
        ticket_id = (resp.data or [{}])[0].get("id", "?")
    except Exception as e:
        return {"status": "error", "message": f"Could not save ticket: {e}"}

    # Step 2: Email admin (non-critical — never blocks the user if SMTP fails)
    try:
        _notify_admin_new_ticket(
            ticket_id=ticket_id,
            ticket_type=ticket_type,
            subject=subject,
            description=desc,
            email=email,
            priority=priority,
        )
    except Exception:
        pass  # Ticket is saved — email failure is silent

    return {"status": "success", "ticket_id": ticket_id}


def update_ticket_status(ticket_id: int, new_status: str, admin_note: str = "") -> dict:
    """Admin: update ticket status and optionally add a note."""
    if new_status not in STATUS_LABELS:
        return {"status": "error", "message": f"Invalid status: {new_status}"}
    try:
        update = {
            "status":     new_status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if admin_note.strip():
            update["admin_note"] = admin_note.strip()[:1000]

        supabase.table("support_tickets").update(update).eq("id", ticket_id).execute()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ══════════════════════════════════════════════════════════════
# READ OPERATIONS
# ══════════════════════════════════════════════════════════════

def get_user_tickets(user_id: str) -> tuple:
    """
    Return (tickets_list, error_message).
    tickets_list is [] on error; error_message is None on success.
    """
    try:
        resp = (
            supabase.table("support_tickets")
            .select("id,ticket_type,subject,status,priority,created_at,updated_at,admin_note")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return (resp.data or []), None
    except Exception as e:
        return [], str(e)


def get_all_tickets(
    status=None,
    ticket_type=None,
    limit: int = 200,
) -> tuple:
    """
    Admin: return (tickets_list, error_message).
    Uses service_role client — bypasses RLS.
    """
    try:
        q = (
            supabase.table("support_tickets")
            .select("id,user_id,email,ticket_type,subject,description,status,priority,created_at,updated_at,admin_note")
            .order("created_at", desc=True)
            .limit(limit)
        )
        if status:
            q = q.eq("status", status)
        if ticket_type:
            q = q.eq("ticket_type", ticket_type)

        resp = q.execute()
        return (resp.data or []), None
    except Exception as e:
        return [], str(e)


def get_ticket_stats() -> dict:
    """Admin: aggregate ticket counts by status and type."""
    all_t, err = get_all_tickets(limit=5000)
    if err:
        return {
            "total": 0, "open": 0, "in_review": 0,
            "resolved": 0, "closed": 0, "by_type": {},
            "_error": err,
        }
    by_status: dict = {}
    by_type:   dict = {}
    for t in all_t:
        s = t.get("status", "open")
        k = t.get("ticket_type", "contact_support")
        by_status[s] = by_status.get(s, 0) + 1
        by_type[k]   = by_type.get(k, 0) + 1
    return {
        "total":     len(all_t),
        "open":      by_status.get("open", 0),
        "in_review": by_status.get("in_review", 0),
        "resolved":  by_status.get("resolved", 0),
        "closed":    by_status.get("closed", 0),
        "by_type":   by_type,
        "_error":    None,
    }


# ══════════════════════════════════════════════════════════════
# EMAIL NOTIFICATIONS
# ══════════════════════════════════════════════════════════════

def _notify_admin_new_ticket(
    ticket_id, ticket_type, subject, description, email, priority
) -> None:
    """Send email to admin when a new ticket is submitted."""
    if not _ADMIN_EMAIL:
        return  # no admin email configured — silent skip

    import html as _html

    type_label     = TICKET_TYPES.get(ticket_type, ticket_type)
    priority_label = PRIORITY_LABELS.get(priority, priority)

    # HTML-escape ALL user-supplied content so curly braces / HTML chars
    # in the description never break the template or inject markup
    safe_subject  = _html.escape(subject[:200])
    safe_email    = _html.escape(email)
    safe_desc     = _html.escape(description[:500]) + ("…" if len(description) > 500 else "")
    safe_type     = _html.escape(type_label)
    safe_priority = _html.escape(priority_label)
    safe_tid      = str(ticket_id)

    body = (
        "<html>"
        "<body style='margin:0;padding:0;background:#0d1117;"
        "font-family:Segoe UI,Arial,sans-serif;'>"
        "<table width='100%' cellpadding='0' cellspacing='0'"
        " style='max-width:580px;margin:32px auto;background:#161b22;"
        "border-radius:14px;border:1px solid #30363d;overflow:hidden;'>"

        "<tr><td style='background:linear-gradient(135deg,#1a3a5c,#1a6fa8);padding:24px 28px;'>"
        "<div style='font-size:1.8rem;'>🎫</div>"
        "<h1 style='color:#fff;font-size:1.2rem;margin:6px 0 2px;'>New Support Ticket #" + safe_tid + "</h1>"
        "<p style='color:#a8d4f5;font-size:0.82rem;margin:0;'>🇮🇳 Indian Trade Intelligence Engine</p>"
        "</td></tr>"

        "<tr><td style='padding:24px 28px;'>"
        "<table width='100%' cellpadding='6' cellspacing='0'>"
        "<tr><td style='color:#8b949e;font-size:0.82rem;width:120px;'>Type</td>"
        "<td style='color:#e6edf3;font-size:0.88rem;font-weight:600;'>" + safe_type + "</td></tr>"
        "<tr><td style='color:#8b949e;font-size:0.82rem;'>Priority</td>"
        "<td style='color:#e6edf3;font-size:0.88rem;font-weight:600;'>" + safe_priority + "</td></tr>"
        "<tr><td style='color:#8b949e;font-size:0.82rem;'>From</td>"
        "<td style='color:#63b3ed;font-size:0.88rem;'>" + safe_email + "</td></tr>"
        "<tr><td style='color:#8b949e;font-size:0.82rem;'>Subject</td>"
        "<td style='color:#e6edf3;font-size:0.88rem;font-weight:600;'>" + safe_subject + "</td></tr>"
        "</table>"

        "<div style='background:#0d1117;border:1px solid #30363d;border-radius:8px;"
        "padding:14px 16px;margin-top:16px;'>"
        "<p style='color:#8b949e;font-size:0.78rem;margin:0 0 6px;'>Description</p>"
        "<p style='color:#c9d1d9;font-size:0.88rem;line-height:1.6;margin:0;white-space:pre-wrap;'>"
        + safe_desc +
        "</p></div>"

        "<p style='color:#6e7681;font-size:0.78rem;margin-top:18px;'>"
        "Log in to Admin Dashboard &rarr; Support Tickets to review and respond.</p>"
        "</td></tr>"

        "<tr><td style='background:#0d1117;padding:12px 28px;"
        "border-top:1px solid #30363d;text-align:center;'>"
        "<p style='color:#484f58;font-size:0.72rem;margin:0;'>"
        "🇮🇳 Trade Intelligence Engine &middot; Admin Notification</p>"
        "</td></tr>"

        "</table></body></html>"
    )

    send_email_alert(
        to_email=_ADMIN_EMAIL,
        subject="[Ticket #" + safe_tid + "] " + safe_priority + " - " + safe_type + " - " + safe_subject[:60],
        body_html=body,
    )