"""
gemini_service.py
Indian Trade Intelligence Engine — Llama 3.3 70B via NVIDIA API
Fixes: better prompts, retry logic, stricter validation, ground-truth anchors
"""

import os
import re
import json
import time
import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("NVIDIA_API_KEY")

if not API_KEY:
    raise ValueError("❌ NVIDIA_API_KEY not found in .env")

API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
MODEL   = "meta/llama-3.3-70b-instruct"

# ─────────────────────────────────────────
# GROUND-TRUTH CONTEXT INJECTED INTO PROMPTS
# Anchors the model to real Indian trade policy
# ─────────────────────────────────────────
IMPORT_CONTEXT = """
Indian Import Duty Facts (2024 — Customs Tariff Act):
- BCD ranges: 0% (essential/pharma APIs), 5% (chemicals/capital goods), 10% (electronics),
  15% (agriculture), 20% (textiles/footwear), 25-100% (alcohol/luxury)
- IGST rates: ONLY 5%, 12%, 18%, or 28% — no other rates exist
- Social Welfare Surcharge (SWS) = always 10% of BCD
- Import Policy categories: Free / Restricted / Prohibited (exact words only)
- SCOMET applies to: dual-use items, defence, nuclear, chemicals (OPCW-listed)
- Licences needed for: arms, narcotics, some chemicals, hazardous waste, ozone-depleting substances
"""

EXPORT_CONTEXT = """
Indian Export Policy Facts (2024 — DGFT Foreign Trade Policy):
- Default status for most goods: Free (no restriction)
- RoDTEP: applies to most manufactured/processed goods; replaced MEIS in 2021
- RoSCTL: ONLY for apparel and made-up textiles — NOT general textiles/yarn
- Prohibited exports: beef, certain wildlife, antiquities, sand, some ozone substances
- Restricted (needs licence): arms, certain chemicals, some varieties of rice/sugar/onion
- Export Duty: most goods = 0%; exceptions: iron ore, some raw hides, rice
"""

KNOWLEDGE_CONTEXT = """
Indian GST Facts (2024 — GST Council):
- 0%: fresh unprocessed food, milk, eggs, books, newspapers, healthcare
- 5%: packed/branded food, edible oils, coal, life-saving medicines, transport services
- 12%: processed food, computers, business travel, medicines not in 5% list
- 18%: most manufactured goods, electronics, most services, chemicals
- 28%: luxury cars, motorcycles >350cc, tobacco, aerated drinks, cement, washing machines
- ITC available: for business inputs used in taxable supplies
- ITC NOT available: personal consumption, motor vehicles (personal), food/beverages, beauty services
"""


# ─────────────────────────────────────────
# CORE LLM CALL WITH RETRY
# ─────────────────────────────────────────
def _call_llama(prompt: str, retries: int = 2) -> dict:
    """Call NVIDIA Llama and return parsed JSON. Retries on JSON parse failure."""
    text = ""
    for attempt in range(retries + 1):
        try:
            headers = {
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a precise Indian trade compliance expert. "
                            "Return ONLY valid JSON — no markdown, no explanation, no preamble. "
                            "Use real Indian trade policy data. Never hallucinate duty rates or HS codes."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 1024,
                "top_p": 0.9,
            }

            response = requests.post(API_URL, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            text = response.json()["choices"][0]["message"]["content"].strip()

            # Strip markdown fences
            clean = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
            clean = re.sub(r"\s*```$", "", clean, flags=re.MULTILINE).strip()

            # Extract JSON object even if model added surrounding text
            match = re.search(r"\{[\s\S]*\}", clean)
            if match:
                clean = match.group(0)

            return json.loads(clean)

        except json.JSONDecodeError:
            if attempt < retries:
                time.sleep(1.5)
                continue
            return {"error": "JSON parsing failed", "raw_response": text[:300]}
        except requests.exceptions.Timeout:
            return {"error": "Request timed out — please retry"}
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                return {"error": "Rate limit hit — please wait a moment and retry"}
            return {"error": f"API error {e.response.status_code}: {e.response.text[:200]}"}
        except Exception as e:
            return {"error": str(e)}

    return {"error": "Failed after retries — please try again"}


# ─────────────────────────────────────────
# VALIDATION
# ─────────────────────────────────────────
def _validate_hs(result: dict) -> dict:
    hs = str(result.get("hs_code", "")).strip()
    if not hs.isdigit() or len(hs) not in (6, 8):
        result["validation_warning"] = (
            f"HS code '{hs}' may be incorrect — ITC-HS codes are 8 digits. "
            "Verify at icegate.gov.in"
        )
    return result


# ─────────────────────────────────────────
# HS CLASSIFICATION
# ─────────────────────────────────────────
def classify_product(product_description: str) -> dict:
    prompt = f"""Classify this product under the Indian ITC-HS Schedule (8-digit).

Product: {product_description}

Rules:
- hs_code MUST be exactly 8 numeric digits
- Use the most specific ITC-HS subheading available
- confidence: 0.0 to 1.0

Return ONLY this JSON:
{{
  "hs_code": "XXXXXXXX",
  "description": "official ITC-HS description",
  "chapter": "Chapter XX - name",
  "confidence": 0.92,
  "note": "classification note or empty string"
}}"""

    result = _call_llama(prompt)
    if "error" not in result:
        result = _validate_hs(result)
    return result


# ─────────────────────────────────────────
# IMPORT INTELLIGENCE
# ─────────────────────────────────────────
def get_import_details(product_description: str) -> dict:
    prompt = f"""You are an Indian customs expert. Analyse this product's import requirements.

{IMPORT_CONTEXT}

Product: {product_description}

IMPORTANT:
- BCD must be a real rate from the Indian Customs Tariff Act
- IGST must be exactly 5, 12, 18, or 28
- SWS is always 10% of BCD
- import_policy_status must be exactly: Free, Restricted, or Prohibited

Return ONLY this JSON:
{{
  "hs_code": "8 digit ITC-HS code",
  "product_description": "brief description",
  "basic_customs_duty_percent": "X%",
  "social_welfare_surcharge_percent": "Y%",
  "igst_percent": "Z%",
  "total_landed_cost_percent": "approx total import duty burden %",
  "import_policy_status": "Free",
  "license_required": false,
  "scomet_applicable": false,
  "special_conditions": "any conditions or empty string",
  "data_confidence": "high"
}}"""

    result = _call_llama(prompt)
    if "error" not in result:
        result = _validate_hs(result)
        igst = str(result.get("igst_percent", "")).replace("%", "").strip()
        if igst and igst not in ["5", "12", "18", "28"]:
            result["validation_warning"] = (
                f"IGST '{igst}%' is non-standard — Indian GST rates are 5/12/18/28%. Verify manually."
            )
    return result


# ─────────────────────────────────────────
# EXPORT INTELLIGENCE
# ─────────────────────────────────────────
def get_export_details(product_description: str) -> dict:
    prompt = f"""You are an Indian export policy expert. Analyse this product's export requirements.

{EXPORT_CONTEXT}

Product: {product_description}

IMPORTANT:
- RoSCTL applies ONLY to apparel/made-up textiles, NOT other goods
- RoDTEP applies to most manufactured goods
- export_policy_status must be exactly: Free, Restricted, or Prohibited

Return ONLY this JSON:
{{
  "hs_code": "8 digit ITC-HS code",
  "product_description": "brief description",
  "export_policy_status": "Free",
  "rodtep_applicable": true,
  "rodtep_rate_percent": "X%",
  "rosctl_applicable": false,
  "export_duty_percent": "0%",
  "export_incentive_notes": "specific schemes available",
  "restricted_countries": "country restrictions or none",
  "documentation_required": "key documents",
  "data_confidence": "high"
}}"""

    result = _call_llama(prompt)
    if "error" not in result:
        result = _validate_hs(result)
    return result


# ─────────────────────────────────────────
# KNOWLEDGE MODE
# ─────────────────────────────────────────
def get_knowledge_details(product_description: str) -> dict:
    prompt = f"""You are an Indian GST and trade compliance advisor. Analyse this product.

{KNOWLEDGE_CONTEXT}

Product: {product_description}

IMPORTANT:
- gst_percent must be exactly 0, 5, 12, 18, or 28
- ITC is available for business use, not personal use

Return ONLY this JSON:
{{
  "hs_code": "8 digit ITC-HS code",
  "product_description": "brief description",
  "gst_percent": "X%",
  "gst_category": "Exempt / Zero-rated / Standard",
  "itc_available": true,
  "itc_conditions": "eligibility conditions",
  "compliance_requirements": "key compliance notes",
  "fssai_required": false,
  "bis_required": false,
  "other_regulatory": "other requirements or none",
  "risk_flags": "risk flags or null",
  "data_confidence": "high"
}}"""

    result = _call_llama(prompt)
    if "error" not in result:
        result = _validate_hs(result)
        gst = str(result.get("gst_percent", "")).replace("%", "").strip()
        if gst and gst not in ["0", "5", "12", "18", "28"]:
            result["validation_warning"] = (
                f"GST '{gst}%' is non-standard — Indian GST rates are 0/5/12/18/28%. Verify manually."
            )
    return result


# ─────────────────────────────────────────
# MASTER ENGINE
# ─────────────────────────────────────────
def trade_intelligence_engine(product_description: str, mode: str) -> dict:
    if not product_description.strip():
        return {"error": "Product description cannot be empty"}

    dispatch = {
        "Import":    get_import_details,
        "Export":    get_export_details,
        "Knowledge": get_knowledge_details,
    }

    fn = dispatch.get(mode)
    if fn is None:
        return {"error": f"Invalid mode '{mode}'. Choose Import, Export, or Knowledge."}

    return fn(product_description)