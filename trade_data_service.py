"""
trade_data_service.py
Parses the ITC Trade Map dataset and provides:
  - Market recommendations (top 5 countries for a product)
  - Country lookup (India's trade stats with a specific country)
  - Dashboard data (charts, trends, tariff data)
  - Future trend scoring for exporters
  - Supabase persistence helpers
"""

import os
import json
from html.parser import HTMLParser
from datetime import datetime
from supabase_service import supabase as _supabase_client


# ─────────────────────────────────────────
# HTML TABLE PARSER (ITC TradeMap .xls files are HTML)
# ─────────────────────────────────────────

class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.current_row = []
        self.current_cell = ""
        self.in_cell = False

    def handle_starttag(self, tag, attrs):
        if tag in ("td", "th"):
            self.in_cell = True
            self.current_cell = ""
        elif tag == "tr":
            self.current_row = []

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self.current_row.append(self.current_cell.strip())
            self.in_cell = False
        elif tag == "tr":
            if any(c.strip() for c in self.current_row):
                self.rows.append(self.current_row)

    def handle_data(self, data):
        if self.in_cell:
            self.current_cell += data


# ─────────────────────────────────────────
# LOAD & PARSE DATASET
# ─────────────────────────────────────────

COLUMN_MAP = [
    "country",
    "export_value_usd_k",       # Value exported in 2024 (USD thousand)
    "trade_balance_usd_k",      # Trade balance 2024
    "share_india_exports_pct",  # Share in India's exports (%)
    "india_share_partner_imports_pct",  # India's share in partner imports (%)
    "growth_5yr_pct",           # Growth 2020-2024 (%, p.a.)
    "growth_1yr_pct",           # Growth 2023-2024 (%, p.a.)
    "world_import_rank",        # World import ranking
    "share_world_imports_pct",  # Share of world imports (%)
    "partner_import_growth_5yr_pct",  # Partner import growth 2020-2024
    "avg_distance_km",          # Avg distance from India (km)
    "supply_concentration",     # Concentration index (lower = easier to enter)
    "avg_tariff_pct",           # Avg tariff faced by India
]


def _safe_float(v: str, default: float = 0.0) -> float:
    try:
        return float(v) if v.strip() else default
    except (ValueError, AttributeError):
        return default


def load_trade_data(filepath: str) -> list[dict]:
    """Parse the ITC TradeMap HTML-disguised XLS file into a list of dicts."""
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        html = f.read()

    parser = _TableParser()
    parser.feed(html)

    records = []
    # rows[0–4] = metadata/headers, rows[5] = World aggregate → skip
    for row in parser.rows[6:]:
        if not row or not row[0].strip():
            continue
        rec = {}
        for i, col in enumerate(COLUMN_MAP):
            rec[col] = row[i].strip() if i < len(row) else ""
        # Add numeric versions for calculations
        rec["_export_value"] = _safe_float(rec["export_value_usd_k"])
        rec["_growth_1yr"]   = _safe_float(rec["growth_1yr_pct"], default=None)
        rec["_growth_5yr"]   = _safe_float(rec["growth_5yr_pct"], default=None)
        rec["_india_share"]  = _safe_float(rec["india_share_partner_imports_pct"])
        rec["_distance"]     = _safe_float(rec["avg_distance_km"])
        rec["_concentration"]= _safe_float(rec["supply_concentration"])
        rec["_world_rank"]   = _safe_float(rec["world_import_rank"])
        rec["_partner_growth"] = _safe_float(rec["partner_import_growth_5yr_pct"])
        rec["_trade_balance"]  = _safe_float(rec["trade_balance_usd_k"])
        records.append(rec)

    return records


# ─────────────────────────────────────────
# OPPORTUNITY SCORE
# Higher = better export opportunity
# Factors: export value, 1yr growth, 5yr growth,
#          partner market size, low supply concentration
# ─────────────────────────────────────────

def _opportunity_score(rec: dict) -> float:
    score = 0.0
    # Large existing trade = proven market (40%)
    score += min(rec["_export_value"] / 1_000_000, 40)
    # Strong recent growth (25%)
    g1 = rec["_growth_1yr"] if rec["_growth_1yr"] is not None else 0
    score += min(max(g1, 0), 25)
    # Growing partner market (15%)
    score += min(max(rec["_partner_growth"], 0), 15)
    # India's penetration potential — low share = room to grow (10%)
    if rec["_india_share"] < 5:
        score += 10
    elif rec["_india_share"] < 15:
        score += 5
    # Low supply concentration = easier to compete (10%)
    if rec["_concentration"] < 0.1:
        score += 10
    elif rec["_concentration"] < 0.2:
        score += 5
    return round(score, 2)


# ─────────────────────────────────────────
# FUTURE TREND SCORE
# Predicts which markets will be hottest in 2-3 years
# Factors: partner import growth, low current India share,
#          world import rank, 5yr CAGR momentum
# ─────────────────────────────────────────

def _future_trend_score(rec: dict) -> float:
    score = 0.0
    # Fast-growing partner market = future demand (35%)
    score += min(max(rec["_partner_growth"], 0), 35)
    # Low India share = untapped potential (25%)
    if rec["_india_share"] < 2:
        score += 25
    elif rec["_india_share"] < 5:
        score += 15
    elif rec["_india_share"] < 10:
        score += 8
    # 5-year CAGR momentum (20%)
    g5 = rec["_growth_5yr"] if rec["_growth_5yr"] is not None else 0
    score += min(max(g5, 0), 20)
    # Large world importer = sustained demand (20%)
    if rec["_world_rank"] <= 10:
        score += 20
    elif rec["_world_rank"] <= 25:
        score += 12
    elif rec["_world_rank"] <= 50:
        score += 6
    return round(score, 2)


# ─────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────

def get_top_markets(records: list[dict], n: int = 5) -> list[dict]:
    """Return top N markets by opportunity score."""
    scored = [
        {**r, "opportunity_score": _opportunity_score(r)}
        for r in records if r["_export_value"] > 0
    ]
    scored.sort(key=lambda x: x["opportunity_score"], reverse=True)
    return scored[:n]


def get_future_trends(records: list[dict], n: int = 10) -> list[dict]:
    """Return top N markets with highest future growth potential."""
    scored = [
        {**r, "future_trend_score": _future_trend_score(r)}
        for r in records if r["_export_value"] > 0
    ]
    scored.sort(key=lambda x: x["future_trend_score"], reverse=True)
    return scored[:n]


def get_country_stats(records: list[dict], country_name: str) -> dict | None:
    """Find a country by name (case-insensitive partial match)."""
    name_lower = country_name.lower()
    for r in records:
        if name_lower in r["country"].lower():
            return {**r, "opportunity_score": _opportunity_score(r),
                    "future_trend_score": _future_trend_score(r)}
    return None


def get_dashboard_data(records: list[dict]) -> dict:
    """Aggregate stats for the dashboard charts."""
    with_value = [r for r in records if r["_export_value"] > 0]

    # Top 15 importers
    top15 = sorted(with_value, key=lambda r: r["_export_value"], reverse=True)[:15]

    # Growth leaders (1yr, min $100M exported)
    growth_leaders = sorted(
        [r for r in with_value if r["_export_value"] >= 100_000 and r["_growth_1yr"] is not None and r["_growth_1yr"] > 0],
        key=lambda r: r["_growth_1yr"],
        reverse=True
    )[:10]

    # Positive vs negative trade balance
    surplus = [r for r in with_value if r["_trade_balance"] > 0]
    deficit = [r for r in with_value if r["_trade_balance"] < 0]

    # Regional buckets (approximate by country name keywords)
    region_map = {
        "Asia": ["China", "Japan", "Korea", "Singapore", "Malaysia", "Thailand",
                 "Vietnam", "Indonesia", "Philippines", "Bangladesh", "Pakistan",
                 "Sri Lanka", "Myanmar", "Cambodia", "Nepal", "India"],
        "Middle East": ["Saudi", "Emirates", "Qatar", "Kuwait", "Bahrain",
                        "Oman", "Iraq", "Iran", "Jordan", "Lebanon", "Israel"],
        "Europe": ["Germany", "France", "Italy", "Netherlands", "Spain", "Belgium",
                   "Sweden", "Poland", "Switzerland", "Austria", "Denmark",
                   "Finland", "Norway", "Czech", "Portugal", "Greece", "United Kingdom"],
        "Americas": ["United States", "Canada", "Brazil", "Mexico", "Argentina",
                     "Colombia", "Chile", "Peru", "Venezuela"],
        "Africa": ["South Africa", "Nigeria", "Kenya", "Ethiopia", "Tanzania",
                   "Egypt", "Morocco", "Algeria", "Ghana", "Angola"],
        "Oceania": ["Australia", "New Zealand"],
    }

    region_totals = {r: 0.0 for r in region_map}
    region_totals["Other"] = 0.0
    for rec in with_value:
        matched = False
        for region, keywords in region_map.items():
            if any(k.lower() in rec["country"].lower() for k in keywords):
                region_totals[region] += rec["_export_value"]
                matched = True
                break
        if not matched:
            region_totals["Other"] += rec["_export_value"]

    total_exports = sum(r["_export_value"] for r in with_value)

    return {
        "top15": top15,
        "growth_leaders": growth_leaders,
        "surplus_count": len(surplus),
        "deficit_count": len(deficit),
        "region_totals": region_totals,
        "total_exports_usd_k": total_exports,
        "total_countries": len(with_value),
        "future_trends": get_future_trends(records, 10),
    }


# ─────────────────────────────────────────
# SUPABASE PERSISTENCE
# ─────────────────────────────────────────

def _create_table_if_missing(conn) -> None:
    """Create trade_market_data table if it doesn't exist yet."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.trade_market_data (
                country                          TEXT PRIMARY KEY,
                export_value_usd_k               NUMERIC,
                trade_balance_usd_k              NUMERIC,
                share_india_exports_pct          NUMERIC,
                india_share_partner_imports_pct  NUMERIC,
                growth_5yr_pct                   NUMERIC,
                growth_1yr_pct                   NUMERIC,
                world_import_rank                INTEGER,
                share_world_imports_pct          NUMERIC,
                partner_import_growth_5yr_pct    NUMERIC,
                avg_distance_km                  NUMERIC,
                supply_concentration             NUMERIC,
                avg_tariff_pct                   NUMERIC,
                opportunity_score                NUMERIC,
                future_trend_score               NUMERIC,
                updated_at                       TIMESTAMPTZ DEFAULT NOW()
            );
            GRANT ALL ON public.trade_market_data TO service_role, anon, authenticated;
            NOTIFY pgrst, 'reload schema';
        """)
        conn.commit()


def upload_trade_data_to_supabase(records: list[dict], supabase_client) -> dict:
    """
    Bulk-upsert all trade records using a direct PostgreSQL connection,
    bypassing PostgREST schema cache issues entirely.

    Requires DATABASE_URL in your .env:
        DATABASE_URL=postgresql://postgres:[password]@db.[project-ref].supabase.co:5432/postgres

    Find it in: Supabase Dashboard → Settings → Database → Connection String → URI
    """
    import os
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        return {
            "status": "error",
            "message": "psycopg2 not installed. Run: pip install psycopg2-binary"
        }

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return {
            "status": "error",
            "message": (
                "DATABASE_URL not found in .env.\n"
                "Add it from: Supabase → Settings → Database → Connection String → URI\n"
                "Format: postgresql://postgres:[YOUR-PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres"
            )
        }

    rows = []
    for r in records:
        rows.append((
            r["country"],
            r["_export_value"],
            r["_trade_balance"],
            _safe_float(r["share_india_exports_pct"]),
            r["_india_share"],
            r["_growth_5yr"],
            r["_growth_1yr"],
            int(r["_world_rank"]) if r["_world_rank"] else None,
            _safe_float(r["share_world_imports_pct"]),
            r["_partner_growth"],
            r["_distance"],
            r["_concentration"],
            _safe_float(r["avg_tariff_pct"]),
            _opportunity_score(r),
            _future_trend_score(r),
            datetime.utcnow(),
        ))

    try:
        conn = psycopg2.connect(db_url)

        # Auto-create table if it doesn't exist
        _create_table_if_missing(conn)

        upsert_sql = """
            INSERT INTO public.trade_market_data (
                country, export_value_usd_k, trade_balance_usd_k,
                share_india_exports_pct, india_share_partner_imports_pct,
                growth_5yr_pct, growth_1yr_pct, world_import_rank,
                share_world_imports_pct, partner_import_growth_5yr_pct,
                avg_distance_km, supply_concentration, avg_tariff_pct,
                opportunity_score, future_trend_score, updated_at
            ) VALUES %s
            ON CONFLICT (country) DO UPDATE SET
                export_value_usd_k              = EXCLUDED.export_value_usd_k,
                trade_balance_usd_k             = EXCLUDED.trade_balance_usd_k,
                share_india_exports_pct         = EXCLUDED.share_india_exports_pct,
                india_share_partner_imports_pct = EXCLUDED.india_share_partner_imports_pct,
                growth_5yr_pct                  = EXCLUDED.growth_5yr_pct,
                growth_1yr_pct                  = EXCLUDED.growth_1yr_pct,
                world_import_rank               = EXCLUDED.world_import_rank,
                share_world_imports_pct         = EXCLUDED.share_world_imports_pct,
                partner_import_growth_5yr_pct   = EXCLUDED.partner_import_growth_5yr_pct,
                avg_distance_km                 = EXCLUDED.avg_distance_km,
                supply_concentration            = EXCLUDED.supply_concentration,
                avg_tariff_pct                  = EXCLUDED.avg_tariff_pct,
                opportunity_score               = EXCLUDED.opportunity_score,
                future_trend_score              = EXCLUDED.future_trend_score,
                updated_at                      = EXCLUDED.updated_at;
        """

        with conn.cursor() as cur:
            psycopg2.extras.execute_values(cur, upsert_sql, rows, page_size=50)
            conn.commit()

        conn.close()
        return {"status": "success", "rows_uploaded": len(rows)}

    except Exception as e:
        return {"status": "error", "message": str(e)}


def get_market_recs_from_supabase(supabase_client, limit: int = 5) -> list[dict]:
    """Fetch top market recommendations from Supabase (fast, no file parsing)."""
    try:
        resp = (
            supabase_client.table("trade_market_data")
            .select("*")
            .order("opportunity_score", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data or []
    except Exception:
        return []

def log_market_lookup(supabase_client, user_id, email, country):
    client = supabase_client or _supabase_client
    try:
        client.table("trade_usage_logs").insert({
            "user_id":   user_id,
            "email":     email,
            "mode":      "CountryLookup",
            "product":   country,
            "timestamp": datetime.utcnow().isoformat(),
        }).execute()
    except Exception:
        pass