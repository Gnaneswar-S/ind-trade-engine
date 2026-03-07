"""
admin_dashboard.py
──────────────────────────────────────────────────────────────
Standalone Admin Dashboard.
Called from app.py:  render_admin_dashboard()
Guard: only users with role == "admin" or is_admin == True reach this.

Metrics:
  • Total Users / Queries / Logins / Queries Today
  • Queries per Mode (Import / Export / Knowledge)
  • Daily query trend — last 14 days (area chart)
  • Most Searched Products (bar chart + table)
  • Top HS Codes (bar chart + table)
  • Full user activity table (queries, logins, last active)
  • Role management widget (upgrade / downgrade)
  • Recent queries across all users
──────────────────────────────────────────────────────────────
"""

import streamlit as st
import plotly.express as px
import pandas as pd
from datetime import datetime, timedelta, timezone

from supabase_service import (
    supabase,
    get_all_users,
    get_all_queries,
    get_platform_stats,
    update_user_role,
)
from support_service import (
    get_all_tickets,
    get_ticket_stats,
    update_ticket_status,
    STATUS_LABELS,
    TICKET_TYPES,
    PRIORITY_LABELS,
)


# ──────────────────────────────────────────────
# DATA LAYER  (all @st.cache_data with 60s TTL)
# ──────────────────────────────────────────────

@st.cache_data(ttl=60, show_spinner=False)
def _fetch_total_logins() -> int:
    try:
        r = (
            supabase.table("auth_logs")
            .select("id", count="exact")
            .eq("action", "LOGIN")
            .execute()
        )
        return r.count or 0
    except Exception:
        return 0


@st.cache_data(ttl=60, show_spinner=False)
def _fetch_top_products(limit: int = 10) -> list:
    """Most-searched product strings."""
    try:
        r = (
            supabase.table("trade_usage_logs")
            .select("product")
            .not_.is_("product", "null")
            .execute()
        )
        counts: dict[str, int] = {}
        for row in r.data or []:
            p = (row.get("product") or "").strip()[:80]
            if p:
                counts[p] = counts.get(p, 0) + 1
        return sorted(
            [{"product": k, "searches": v} for k, v in counts.items()],
            key=lambda x: x["searches"], reverse=True,
        )[:limit]
    except Exception:
        return []


@st.cache_data(ttl=60, show_spinner=False)
def _fetch_top_hs_codes(limit: int = 10) -> list:
    """Most frequently returned HS codes."""
    try:
        r = (
            supabase.table("trade_usage_logs")
            .select("hs_code")
            .not_.is_("hs_code", "null")
            .execute()
        )
        counts: dict[str, int] = {}
        for row in r.data or []:
            hs = (row.get("hs_code") or "").strip()
            if hs and hs.isdigit():
                counts[hs] = counts.get(hs, 0) + 1
        return sorted(
            [{"hs_code": k, "occurrences": v} for k, v in counts.items()],
            key=lambda x: x["occurrences"], reverse=True,
        )[:limit]
    except Exception:
        return []


@st.cache_data(ttl=60, show_spinner=False)
def _fetch_daily_trend(days: int = 14) -> list:
    """Query volume per day for the last N days."""
    try:
        since = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).isoformat()
        r = (
            supabase.table("trade_usage_logs")
            .select("timestamp")
            .gte("timestamp", since)
            .execute()
        )
        counts: dict[str, int] = {}
        for row in r.data or []:
            day = (row.get("timestamp") or "")[:10]
            if day:
                counts[day] = counts.get(day, 0) + 1

        result = []
        for i in range(days):
            day = (
                datetime.now(timezone.utc) - timedelta(days=days - 1 - i)
            ).strftime("%Y-%m-%d")
            result.append({"Date": day, "Queries": counts.get(day, 0)})
        return result
    except Exception:
        return []


@st.cache_data(ttl=60, show_spinner=False)
def _fetch_user_activity() -> list:
    """Per-user summary: queries, logins, last active."""
    try:
        profiles = supabase.table("profiles").select("user_id,email,role").execute()
        rows = []
        for p in profiles.data or []:
            uid = p["user_id"]

            q = (
                supabase.table("trade_usage_logs")
                .select("id", count="exact")
                .eq("user_id", uid)
                .execute()
            )
            l = (
                supabase.table("auth_logs")
                .select("id", count="exact")
                .eq("user_id", uid)
                .eq("action", "LOGIN")
                .execute()
            )
            last = (
                supabase.table("trade_usage_logs")
                .select("timestamp")
                .eq("user_id", uid)
                .order("timestamp", desc=True)
                .limit(1)
                .execute()
            )
            last_active = ""
            if last.data:
                last_active = (last.data[0].get("timestamp") or "")[:10]

            rows.append({
                "Email":       p.get("email", ""),
                "Role":        (p.get("role") or "free").upper(),
                "Queries":     q.count or 0,
                "Logins":      l.count or 0,
                "Last Active": last_active or "Never",
                "_uid":        uid,
            })
        return sorted(rows, key=lambda x: x["Queries"], reverse=True)
    except Exception:
        return []


# ──────────────────────────────────────────────
# CHART HELPERS
# ──────────────────────────────────────────────

_DARK_BG = "rgba(0,0,0,0)"
_GRID    = "#2d3748"

def _chart_layout(fig, height=320):
    fig.update_layout(
        height=height,
        margin=dict(t=24, b=12, l=0, r=0),
        paper_bgcolor=_DARK_BG,
        plot_bgcolor=_DARK_BG,
        font=dict(color="#c9d1d9", size=11),
        xaxis=dict(showgrid=False, color="#c9d1d9"),
        yaxis=dict(showgrid=True, gridcolor=_GRID, color="#c9d1d9"),
    )
    return fig


# ──────────────────────────────────────────────
# MAIN RENDER
# ──────────────────────────────────────────────

def render_admin_dashboard() -> None:
    """
    Entry point — called from app.py tab_admin().
    Must only be reached by admin users (guard is in app.py main()).
    """

    # ── HEADER ────────────────────────────────────
    st.markdown("""
    <div style="background:linear-gradient(135deg,#1a3a5c 0%,#1a6fa8 100%);
                border-radius:12px;padding:20px 26px;margin-bottom:18px;">
      <h2 style="color:#ffffff;margin:0;font-size:1.35rem;font-weight:700;">
        👤  Admin Dashboard
      </h2>
      <p style="color:#a8d4f5;margin:5px 0 0;font-size:0.82rem;">
        Platform-wide metrics · Live Supabase data · Cache refreshes every 60 s
      </p>
    </div>
    """, unsafe_allow_html=True)

    _, refresh_col = st.columns([6, 1])
    with refresh_col:
        if st.button("🔄 Refresh", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    # ── KPI ROW ───────────────────────────────────
    st.markdown("#### 📊 Platform Overview")
    stats = get_platform_stats()

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("👥 Total Users",     stats.get("total_users", 0))
    k2.metric("🔍 Total Queries",   stats.get("total_queries", 0))
    k3.metric("📅 Queries Today",   stats.get("queries_today", 0))
    k4.metric("🔑 Total Logins",    _fetch_total_logins())
    by_mode = stats.get("by_mode") or {}
    k5.metric(
        "🏆 Top Mode",
        max(by_mode, key=by_mode.get) if by_mode else "—",
    )

    if stats.get("_errors"):
        with st.expander("⚠️ Data errors detected — click to diagnose", expanded=True):
            for err in stats["_errors"]:
                st.error(f"❌ {err}")
            st.warning(
                "**Likely causes:**\n"
                "1. RLS policy is blocking service_role reads — run the SQL fix below\n"
                "2. Table does not exist — run the migration SQL\n"
                "3. Wrong Supabase key in .env"
            )
            st.code("""-- Run this in Supabase → SQL Editor to fix RLS blocking service_role:
DROP POLICY IF EXISTS "Service role full access to usage" ON trade_usage_logs;
CREATE POLICY "Service role full access to usage"
  ON trade_usage_logs FOR ALL USING (true)
  WITH CHECK (true);

DROP POLICY IF EXISTS "Service role full access to auth_logs" ON auth_logs;
CREATE POLICY "Service role full access to auth_logs"
  ON auth_logs FOR ALL USING (true)
  WITH CHECK (true);

DROP POLICY IF EXISTS "Service role full access to profiles" ON profiles;
CREATE POLICY "Service role full access to profiles"
  ON profiles FOR ALL USING (true)
  WITH CHECK (true);

-- Also verify service_role key is set (not anon key):
-- In .env: SUPABASE_SERVICE_KEY=eyJ... (must start with eyJ, Settings > API > service_role)
""", language="sql")

    st.markdown("---")

    # ── ROW 1: Queries by Mode  +  Daily Trend ────
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("##### Queries by Mode")
        if by_mode:
            fig = px.pie(
                values=list(by_mode.values()),
                names=list(by_mode.keys()),
                color_discrete_sequence=["#1A6FA8", "#27AE60", "#E67E22", "#8E44AD"],
                hole=0.42,
            )
            fig.update_traces(textposition="inside", textinfo="percent+label",
                              textfont_size=11)
            fig.update_layout(
                height=300,
                margin=dict(t=10, b=10, l=0, r=0),
                showlegend=True,
                legend=dict(orientation="h", y=-0.12, font=dict(color="#c9d1d9")),
                paper_bgcolor=_DARK_BG,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No query data yet.")

    with col2:
        st.markdown("##### Daily Query Volume — Last 14 Days")
        trend = _fetch_daily_trend(14)
        if trend:
            df_t = pd.DataFrame(trend)
            fig2 = px.area(
                df_t, x="Date", y="Queries",
                color_discrete_sequence=["#1A6FA8"],
            )
            fig2.update_traces(
                fill="tozeroy",
                line=dict(color="#1A6FA8", width=2),
                fillcolor="rgba(26,111,168,0.25)",
            )
            _chart_layout(fig2, height=300)
            fig2.update_xaxes(tickangle=-30, nticks=7)
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("No trend data yet.")

    st.markdown("---")

    # ── ROW 2: Top Products  +  Top HS Codes ──────
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("##### 🔎 Most Searched Products")
        products = _fetch_top_products(10)
        if products:
            df_p = pd.DataFrame(products)
            fig3 = px.bar(
                df_p, x="searches", y="product", orientation="h",
                color="searches", color_continuous_scale="Blues",
                labels={"searches": "Searches", "product": "Product"},
            )
            fig3.update_layout(
                yaxis={"categoryorder": "total ascending"},
                coloraxis_showscale=False,
            )
            _chart_layout(fig3, height=340)
            st.plotly_chart(fig3, use_container_width=True)

            with st.expander("📋 Full Product Table"):
                st.dataframe(df_p, use_container_width=True, hide_index=True)
        else:
            st.info("No product data yet.")

    with col2:
        st.markdown("##### 📦 Top HS Codes Returned")
        hs_data = _fetch_top_hs_codes(10)
        if hs_data:
            df_hs = pd.DataFrame(hs_data)
            fig4 = px.bar(
                df_hs, x="occurrences", y="hs_code", orientation="h",
                color="occurrences", color_continuous_scale="Greens",
                labels={"occurrences": "Count", "hs_code": "HS Code"},
            )
            fig4.update_layout(
                yaxis={"categoryorder": "total ascending"},
                coloraxis_showscale=False,
            )
            _chart_layout(fig4, height=340)
            st.plotly_chart(fig4, use_container_width=True)

            with st.expander("📋 Full HS Code Table"):
                st.dataframe(df_hs, use_container_width=True, hide_index=True)
        else:
            st.info("No HS code data yet.")

    st.markdown("---")

    # ── USER ACTIVITY TABLE ───────────────────────
    st.markdown("#### 👥 User Activity")
    activity = _fetch_user_activity()
    if activity:
        display_cols = ["Email", "Role", "Queries", "Logins", "Last Active"]
        df_act = pd.DataFrame(activity)[display_cols]
        st.dataframe(df_act, use_container_width=True, hide_index=True)
    else:
        st.info("No user data yet.")

    st.markdown("---")

    # ── ROLE MANAGEMENT ───────────────────────────
    st.markdown("#### 🔧 User Role Management")

    users = get_all_users()
    if users:
        role_options = ["free", "user", "pro", "admin"]
        emails = [u.get("email", "") for u in users]

        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            sel_email = st.selectbox(
                "Select User", emails, key="adm_sel_email",
                help="Select the user to modify",
            )
        with c2:
            curr = next(
                (u.get("role", "free") for u in users if u.get("email") == sel_email),
                "free",
            )
            new_role = st.selectbox(
                "New Role", role_options,
                index=role_options.index(curr) if curr in role_options else 0,
                key="adm_new_role",
            )
        with c3:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("✅ Apply Role", type="primary",
                         use_container_width=True, key="adm_apply"):
                uid = next(
                    (u["user_id"] for u in users if u.get("email") == sel_email),
                    None,
                )
                if uid:
                    res = update_user_role(uid, new_role)
                    if res["status"] == "success":
                        st.success(f"✅ **{sel_email}** → **{new_role.upper()}**")
                        st.cache_data.clear()
                    else:
                        st.error(f"❌ {res['message']}")

        st.caption(
            "**Role daily query limits:**  "
            "Free = 10  ·  User = 50  ·  Pro = 200  ·  Admin = Unlimited"
        )
    else:
        st.info("No users found.")

    st.markdown("---")

    # ── RECENT QUERIES ────────────────────────────
    st.markdown("#### 📋 Recent Queries — All Users")
    limit_n = st.slider("Show last N queries", 10, 200, 50,
                        step=10, key="adm_q_limit")
    queries, _q_err = get_all_queries(limit=limit_n)
    if _q_err:
        st.error(
            f"❌ Cannot read trade_usage_logs: {_q_err}\n\n"
            "Run the RLS fix SQL shown in the Platform Overview section above."
        )
    elif queries:
        df_q = pd.DataFrame([{
            "Time":    (q.get("timestamp") or "")[:19].replace("T", " "),
            "Email":   q.get("email", ""),
            "Mode":    q.get("mode", ""),
            "Product": (q.get("product") or "")[:72]
                       + ("…" if len(q.get("product") or "") > 72 else ""),
            "HS Code": q.get("hs_code", ""),
        } for q in queries])
        st.dataframe(df_q, use_container_width=True, hide_index=True)
    else:
        st.info("No queries yet. Run a Trade Analysis to see data here.")

    st.markdown("---")

    # ── SUPPORT TICKETS ───────────────────────────
    st.markdown("#### 🎫 Support Tickets")

    tstats = get_ticket_stats()

    if tstats.get("_error"):
        st.warning(
            f"⚠️ Support tickets table not found or inaccessible: `{tstats['_error']}`\n\n"
            "Run **`support_tickets_migration.sql`** in Supabase → SQL Editor to create it."
        )
    else:
        # KPI row
        tk1, tk2, tk3, tk4, tk5 = st.columns(5)
        tk1.metric("🎫 Total",     tstats["total"])
        tk2.metric("🟡 Open",      tstats["open"])
        tk3.metric("🔵 In Review", tstats["in_review"])
        tk4.metric("🟢 Resolved",  tstats["resolved"])
        tk5.metric("⚫ Closed",    tstats["closed"])

    # Filters — always rendered first so variables are always defined
    filt_col1, filt_col2 = st.columns(2)
    with filt_col1:
        _filter_status = st.selectbox(
            "Filter by Status",
            ["All", "open", "in_review", "resolved", "closed"],
            key="adm_ticket_status_filter",
            format_func=lambda x: "All Statuses" if x == "All" else STATUS_LABELS.get(x, x),
        )
    with filt_col2:
        _filter_type = st.selectbox(
            "Filter by Type",
            ["All"] + list(TICKET_TYPES.keys()),
            key="adm_ticket_type_filter",
            format_func=lambda x: "All Types" if x == "All" else TICKET_TYPES[x],
        )

    # Ticket type breakdown chart — only shown when there is data
    if tstats["by_type"]:
        type_data = [
            {"Type": TICKET_TYPES.get(k, k), "Count": v}
            for k, v in tstats["by_type"].items()
        ]
        df_types = pd.DataFrame(type_data)
        fig_t = px.bar(
            df_types, x="Type", y="Count",
            color="Type",
            color_discrete_sequence=["#1A6FA8", "#E67E22", "#27AE60"],
            title="Tickets by Category",
        )
        fig_t.update_layout(
            height=240, showlegend=False,
            margin=dict(t=32, b=8, l=0, r=0),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#c9d1d9"),
        )
        st.plotly_chart(fig_t, use_container_width=True)

    # Tickets table
    _s_arg = None if _filter_status == "All" else _filter_status
    _t_arg = None if _filter_type   == "All" else _filter_type
    all_tickets, _tkt_err = get_all_tickets(status=_s_arg, ticket_type=_t_arg, limit=100)

    if _tkt_err:
        st.error(
            f"❌ Could not load tickets: {_tkt_err}\n\n"
            "**Most likely cause:** The `support_tickets` table doesn't exist yet.\n"
            "Run `support_tickets_migration.sql` in Supabase → SQL Editor."
        )
    elif all_tickets:
        for tkt in all_tickets:
            _tid    = tkt.get("id")
            _status = tkt.get("status", "open")
            _prio   = tkt.get("priority", "medium")
            _type   = TICKET_TYPES.get(tkt.get("ticket_type",""), tkt.get("ticket_type",""))
            _subj   = tkt.get("subject", "")
            _email  = tkt.get("email", "")
            _ts     = (tkt.get("created_at") or "")[:10]
            _note   = tkt.get("admin_note", "") or ""

            _status_icon = STATUS_LABELS.get(_status, _status)
            _prio_icon   = PRIORITY_LABELS.get(_prio, _prio)

            with st.expander(
                f"{_status_icon} · {_prio_icon} · **{_subj[:60]}** — {_email} ({_ts})",
                expanded=False,
            ):
                col_info, col_action = st.columns([3, 1])

                with col_info:
                    st.markdown(f"**Type:** {_type}")
                    st.markdown(f"**Description:**")
                    st.markdown(
                        f"<div style='background:#0d1117;border:1px solid #30363d;"
                        f"border-radius:8px;padding:12px;font-size:0.85rem;color:#c9d1d9;"
                        f"line-height:1.6;'>{tkt.get('description','')}</div>",
                        unsafe_allow_html=True,
                    )
                    if _note:
                        st.markdown(
                            f"<div style='background:#1a2a1a;border:1px solid #27ae60;"
                            f"border-radius:8px;padding:10px;margin-top:8px;"
                            f"font-size:0.82rem;color:#48bb78;'>"
                            f"📝 <strong>Admin Note:</strong> {_note}</div>",
                            unsafe_allow_html=True,
                        )

                with col_action:
                    st.markdown("**Update Status**")
                    _new_status = st.selectbox(
                        "Status",
                        list(STATUS_LABELS.keys()),
                        index=list(STATUS_LABELS.keys()).index(_status),
                        key=f"tkt_status_{_tid}",
                        format_func=lambda x: STATUS_LABELS[x],
                    )
                    _admin_note_input = st.text_area(
                        "Add Note", value="", height=80,
                        placeholder="Optional note to user…",
                        key=f"tkt_note_{_tid}",
                    )
                    if st.button(
                        "✅ Save", key=f"tkt_save_{_tid}",
                        use_container_width=True, type="primary",
                    ):
                        res = update_ticket_status(
                            _tid, _new_status,
                            _admin_note_input.strip(),
                        )
                        if res["status"] == "success":
                            st.success("Updated!")
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(res["message"])
    else:
        st.info("No tickets found matching the current filters.")

    st.markdown("---")

    # ── REVENUE ANALYTICS (FUTURE) ────────────────
    st.markdown("#### 💰 Revenue Analytics")
    st.markdown("""
    <div style="background:#161b22;border:1px dashed #30363d;border-radius:12px;
                padding:32px;text-align:center;">
      <div style="font-size:2.5rem;margin-bottom:12px;">📊</div>
      <h3 style="color:#e2e8f0;margin:0 0 8px;font-size:1.1rem;">Coming Soon</h3>
      <p style="color:#8b949e;font-size:0.88rem;margin:0 0 20px;line-height:1.6;">
        Revenue analytics will track subscription upgrades, plan conversions,<br>
        monthly recurring revenue (MRR), and user lifetime value.
      </p>

      <div style="display:flex;justify-content:center;gap:24px;flex-wrap:wrap;margin-top:16px;">
        <div style="background:#0d1117;border:1px solid #30363d;border-radius:10px;
                    padding:16px 24px;min-width:130px;">
          <div style="font-size:1.4rem;">💳</div>
          <div style="color:#8b949e;font-size:0.75rem;margin-top:4px;">MRR</div>
          <div style="color:#6e7681;font-size:1.1rem;font-weight:700;">—</div>
        </div>
        <div style="background:#0d1117;border:1px solid #30363d;border-radius:10px;
                    padding:16px 24px;min-width:130px;">
          <div style="font-size:1.4rem;">📈</div>
          <div style="color:#8b949e;font-size:0.75rem;margin-top:4px;">Conversions</div>
          <div style="color:#6e7681;font-size:1.1rem;font-weight:700;">—</div>
        </div>
        <div style="background:#0d1117;border:1px solid #30363d;border-radius:10px;
                    padding:16px 24px;min-width:130px;">
          <div style="font-size:1.4rem;">👑</div>
          <div style="color:#8b949e;font-size:0.75rem;margin-top:4px;">Pro Users</div>
          <div style="color:#6e7681;font-size:1.1rem;font-weight:700;">{pro_count}</div>
        </div>
        <div style="background:#0d1117;border:1px solid #30363d;border-radius:10px;
                    padding:16px 24px;min-width:130px;">
          <div style="font-size:1.4rem;">🆓</div>
          <div style="color:#8b949e;font-size:0.75rem;margin-top:4px;">Free Users</div>
          <div style="color:#6e7681;font-size:1.1rem;font-weight:700;">{free_count}</div>
        </div>
      </div>

      <p style="color:#484f58;font-size:0.75rem;margin-top:20px;">
        Integrate Razorpay / Stripe to unlock full revenue tracking
      </p>
    </div>
    """.format(
        pro_count  = sum(1 for u in (get_all_users() or []) if u.get("role") == "pro"),
        free_count = sum(1 for u in (get_all_users() or []) if u.get("role") == "free"),
    ), unsafe_allow_html=True)