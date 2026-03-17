"""
hs_engine.py
🇮🇳 AI HS Code Classification Engine
────────────────────────────────────────────────────────────────
Combines Llama 3.3 70B AI classification with static dataset lookup.
Dataset files in data/ folder (JSON, loaded once at startup):
  data/hs_codes.json        — ITC-HS 2022 (12,500+ entries)
  data/duty_structure.json  — BCD + IGST + SWS by HS code
  data/gst_rates.json       — GST rate by HS code
  data/rodtep_rates.json    — RoDTEP rates by HS code
  data/scomet_list.json     — SCOMET restricted items
  data/dgft_policy.json     — DGFT import/export policy by HS
────────────────────────────────────────────────────────────────
"""

import os
import json
from pathlib import Path
from nvidia_service import _call_llama

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))

# ── cached dataset holders ─────────────────────────────────────
_CACHE = {}

def _db(name: str) -> dict:
    if name not in _CACHE:
        p = DATA_DIR / f"{name}.json"
        _CACHE[name] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return _CACHE[name]


# ═══════════════════════════════════════════════════════════════
# DATABASE LOOKUP
# ═══════════════════════════════════════════════════════════════

def lookup_hs_code(hs_code: str) -> dict:
    """Return all dataset fields for a known HS code (8, 6, or 4 digit lookup)."""
    hs = str(hs_code).strip().zfill(8)[:8]
    keys = [hs, hs[:6], hs[:4], hs[:2]]

    result = {"hs_code": hs, "source": "database"}

    for d_name, keys_to_try in [
        ("hs_codes",       keys),
        ("duty_structure", keys),
        ("gst_rates",      keys),
        ("rodtep_rates",   keys),
        ("scomet_list",    keys),
        ("dgft_policy",    keys),
    ]:
        db = _db(d_name)
        entry = next((db[k] for k in keys_to_try if k in db), None)
        if entry and isinstance(entry, dict):
            result.update({k: v for k, v in entry.items() if k not in result})

    # SCOMET flag
    scomet_db = _db("scomet_list")
    result["scomet_restricted"] = any(k in scomet_db for k in keys)

    # Calculate total import burden if we have BCD + IGST
    try:
        bcd  = float(str(result.get("bcd",  "0")).replace("%","") or 0)
        igst = float(str(result.get("igst", "0")).replace("%","") or 0)
        sws  = bcd * 0.10
        total = ((1+bcd/100)*(1+sws/100)*(1+igst/100) - 1) * 100
        result["total_import_burden_pct"] = f"{total:.1f}%"
    except Exception:
        pass

    result["verify_url"] = f"https://www.icegate.gov.in/Webappl/tcc?tariff={hs}"
    return result


# ═══════════════════════════════════════════════════════════════
# AI CLASSIFICATION + DATASET ENRICHMENT
# ═══════════════════════════════════════════════════════════════

def classify_and_enrich(product_description: str) -> dict:
    """AI classifies product → HS code, then database enriches with rates."""
    prompt = f"""Classify this product under Indian ITC-HS 2022 Schedule (8-digit).

Product: {product_description}

Rules:
- hs_code MUST be exactly 8 numeric digits
- Use the most specific subheading available
- Consider material, end-use, and processing state

Return ONLY JSON:
{{"hs_code":"XXXXXXXX","hs_description":"official description","chapter_no":"XX","chapter_name":"Chapter title","section":"Section I-XXI","classification_rationale":"2-sentence reason","confidence":0.92,"alternate_codes":["YYYYYYYY"],"note":"or empty string"}}"""

    ai = _call_llama(prompt)
    if "error" in ai:
        return ai

    hs = str(ai.get("hs_code","")).strip()
    if not hs.isdigit() or len(hs) not in (6, 8):
        ai["validation_warning"] = f"HS '{hs}' format non-standard — verify at icegate.gov.in"

    # Merge with database
    db_data = lookup_hs_code(hs) if hs else {}
    merged = {**ai}
    for k, v in db_data.items():
        if k not in merged or merged[k] in (None, "", "N/A"):
            merged[k] = v
    merged["_db_enriched"] = bool(db_data)
    return merged


# ═══════════════════════════════════════════════════════════════
# SHIPMENT COST CALCULATOR
# ═══════════════════════════════════════════════════════════════

def calculate_shipment_cost(
    product: str,
    hs_code: str,
    origin_port: str,
    destination_port: str,
    weight_kg: float,
    volume_cbm: float,
    shipment_value_usd: float,
    direction: str = "Export",
) -> dict:
    """Estimate full shipment cost breakdown including all duties and charges."""
    prompt = (
        "Calculate complete shipment cost for this Indian trade transaction.\n\n"
        "Product: " + product + "\n"
        "HS Code: " + hs_code + "\n"
        "Direction: " + direction + "\n"
        "Origin Port: " + origin_port + "\n"
        "Destination Port: " + destination_port + "\n"
        "Weight: " + str(weight_kg) + " kg\n"
        "Volume: " + str(volume_cbm) + " CBM\n"
        "Cargo Value: USD " + str(shipment_value_usd) + "\n\n"
        "Provide realistic 2024 freight estimates. Include all Indian port charges.\n\n"
        "Return ONLY JSON:\n"
        '{"product":"' + product + '",'
        '"direction":"' + direction + '",'
        '"origin":"' + origin_port + '",'
        '"destination":"' + destination_port + '",'
        '"cargo_value_usd":' + str(shipment_value_usd) + ','
        '"freight_charges":{"sea_freight_usd":0,"airfreight_usd":0,"recommended_mode":"Sea","mode_reason":"reason"},'
        '"origin_charges":{"inland_transport_inr":0,"port_handling_inr":0,"customs_examination_inr":0,"seal_charges_inr":0,"total_origin_inr":0},'
        '"destination_charges":{"port_handling_usd":0,"customs_duty_usd":0,"local_delivery_usd":0,"total_destination_usd":0},'
        '"insurance":{"recommended_value_usd":0,"premium_usd":0,"note":"0.15-0.25% of CIF value"},'
        '"indian_port_charges":{"thc_inr":0,"documentation_inr":0,"ams_inr":0,"customs_agent_inr":0},'
        '"total_cost_summary":{"export_cost_inr_approx":0,"import_landed_cost_usd":0,"cost_as_pct_cargo_value":"X%"},'
        '"transit_time_days":{"sea":21,"air":5},'
        '"recommended_freight_forwarders":["Agility India","DB Schenker India","Maersk India"],'
        '"notes":"specific cost-saving tips"}'
    )
    return _call_llama(prompt)


# ═══════════════════════════════════════════════════════════════
# DATASET STATUS  (for admin panel)
# ═══════════════════════════════════════════════════════════════

def get_dataset_status() -> dict:
    datasets = {
        "hs_codes":       "ITC-HS 2022 Schedule",
        "duty_structure": "BCD + IGST + SWS",
        "gst_rates":      "GST Rates by HS Code",
        "rodtep_rates":   "RoDTEP Export Rates",
        "scomet_list":    "SCOMET Restricted Items",
        "dgft_policy":    "DGFT Import/Export Policy",
    }
    status = {}
    for key, label in datasets.items():
        p = DATA_DIR / f"{key}.json"
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                status[key] = {"label": label, "loaded": True, "records": len(data), "file": str(p)}
            except Exception as e:
                status[key] = {"label": label, "loaded": False, "records": 0, "error": str(e)}
        else:
            status[key] = {"label": label, "loaded": False, "records": 0, "error": "File not found"}
    return status