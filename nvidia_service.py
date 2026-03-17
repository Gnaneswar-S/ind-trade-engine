"""
nvidia_service.py
Indian Trade Intelligence Engine — Llama 3.3 70B via NVIDIA API
────────────────────────────────────────────────────────────────
Security: API key from env only, never hardcoded
Performance: in-memory response cache for identical prompts
Reliability: retry with exponential backoff, 120s timeout
Logging: structured, no secrets in logs
────────────────────────────────────────────────────────────────
"""

import os
import re
import json
import time
import hashlib
import logging
import requests
from dotenv import load_dotenv
import streamlit as st

load_dotenv()

logger = logging.getLogger("nvidia_service")

# ── Secure config — env or secrets ─────────────────────────────────────
try:
    API_KEY = st.secrets["NVIDIA_API_KEY"]
except (KeyError, Exception):
    API_KEY = os.getenv("NVIDIA_API_KEY", "").strip()
if not API_KEY:
    raise ValueError("❌ NVIDIA_API_KEY not found in Streamlit secrets or .env — add it to your environment")

API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
MODEL   = "meta/llama-3.3-70b-instruct"

# ── Response cache (in-memory, keyed by prompt hash) ─────────────
_RESPONSE_CACHE: dict[str, dict] = {}
_CACHE_MAX_SIZE = 200

def _cache_key(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]

def _cache_get(prompt: str) -> dict | None:
    return _RESPONSE_CACHE.get(_cache_key(prompt))

def _cache_set(prompt: str, result: dict) -> None:
    if len(_RESPONSE_CACHE) >= _CACHE_MAX_SIZE:
        oldest_key = next(iter(_RESPONSE_CACHE))
        del _RESPONSE_CACHE[oldest_key]
    _RESPONSE_CACHE[_cache_key(prompt)] = result

def clear_response_cache() -> None:
    _RESPONSE_CACHE.clear()
    logger.info("Response cache cleared")

# ── Ground-truth context injected into prompts ───────────────────
IMPORT_CONTEXT = """
CONTEXT: You are analyzing imports INTO INDIA. All duties, taxes, and policies are INDIA's — NOT the USA, UK, EU, or any other country.

Indian Import Duty Facts (2024 — Indian Customs Tariff Act, effective April 2024):
- BCD (Basic Customs Duty) is charged by INDIA on goods arriving INTO India
- Turmeric/spices: BCD 30-100% (agricultural protection); Edible oils: 5-100%; Electronics: 10-20%
- BCD ranges: 0% (pharma APIs, life-saving drugs), 5% (chemicals, capital goods not made in India),
  10% (electronics, metals), 15-30% (agriculture, processed food), 40-100% (luxury, alcohol, tobacco)
- Agriculture BCD examples: Rice 80%, Wheat 50%, Sugar 100%, Spices 30-150%, Turmeric 30%
- IGST rates: ONLY 5%, 12%, 18%, or 28% (food/agriculture typically 0-5%, manufactured goods 12-18%)
- Social Welfare Surcharge (SWS) = always 10% of BCD
- Total effective duty = BCD + SWS(10% of BCD) + IGST on (CIF + BCD + SWS)
- Import Policy categories: Free / Restricted / Prohibited (exact words only)
- SCOMET applies to: dual-use items, defence, nuclear, chemicals (OPCW-listed)
- Special: MEIS/incentive schemes are EXPORT schemes, not import
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

SYSTEM_PROMPT = (
    "You are a precise Indian trade compliance expert. "
    "Return ONLY valid JSON — no markdown, no explanation, no preamble. "
    "Use real Indian trade policy data. Never hallucinate duty rates or HS codes."
)


# ════════════════════════════════════════════════════════════════════
# CORE LLM CALL
# ════════════════════════════════════════════════════════════════════

def _try_recover_json(text: str):
    """
    Attempt to recover a valid JSON object from a truncated LLM response.
    Strategy 1: find outermost { } pair.
    Strategy 2: balance open brackets/braces and retry parse.
    Returns parsed dict or None.
    """
    if not text:
        return None
    # Strip markdown fences
    clean = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    clean = re.sub(r"\s*```$", "", clean, flags=re.MULTILINE).strip()
    # Strategy 1: outermost JSON object
    m = re.search(r"\{[\s\S]*\}", clean)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    # Strategy 2: balance truncated JSON
    start = clean.find("{")
    if start < 0:
        return None
    candidate = clean[start:]
    open_b = candidate.count("{") - candidate.count("}")
    open_a = candidate.count("[") - candidate.count("]")
    if open_b > 0 or open_a > 0:
        # Strip trailing incomplete token
        fixed = re.sub(r',\s*"[^"]*"\s*:\s*"[^"]*$', "", candidate.rstrip())
        fixed = re.sub(r',\s*"[^"]*"\s*:\s*$', "", fixed)
        fixed = re.sub(r',\s*$', "", fixed)
        fixed = fixed + ("}" * open_b) + ("]" * open_a)
        ob2 = fixed.count("{") - fixed.count("}")
        oa2 = fixed.count("[") - fixed.count("]")
        if ob2 > 0 or oa2 > 0:
            fixed += ("}" * max(0, ob2)) + ("]" * max(0, oa2))
        try:
            result = json.loads(fixed)
            if isinstance(result, dict) and result:
                return result
        except json.JSONDecodeError:
            pass
    return None


def _call_llama(
    prompt: str,
    retries: int = 3,
    use_cache: bool = True,
    max_tokens: int = 1024,
) -> dict:
    """
    Call NVIDIA Llama 3.3 70B and return parsed JSON.
    - Retries up to `retries` times on JSON parse failure
    - Exponential backoff on rate limit / server errors
    - In-memory caching for identical prompts
    - Never logs the API key or raw user data
    """
    if use_cache:
        cached = _cache_get(prompt)
        if cached:
            logger.debug("Serving from response cache")
            return cached

    text = ""
    for attempt in range(retries + 1):
        try:
            headers = {
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type":  "application/json",
            }
            payload = {
                "model":       MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt},
                ],
                "temperature": 0.1,
                "max_tokens":  max_tokens,
                "top_p":       0.9,
            }

            response = requests.post(
                API_URL, headers=headers, json=payload, timeout=120
            )
            response.raise_for_status()
            text = response.json()["choices"][0]["message"]["content"].strip()
            logger.debug(f"NVIDIA API call successful (attempt {attempt + 1})")

            # Strip markdown fences
            clean = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
            clean = re.sub(r"\s*```$",           "", clean, flags=re.MULTILINE).strip()

            # Extract JSON object even if model added surrounding text
            match = re.search(r"\{[\s\S]*\}", clean)
            if match:
                clean = match.group(0)

            result = json.loads(clean)

            if use_cache:
                _cache_set(prompt, result)

            return result

        except json.JSONDecodeError:
            logger.warning(f"JSON decode failed on attempt {attempt + 1}: {text[:200]}")
            # Try to salvage truncated JSON by finding the largest valid object
            recovered = _try_recover_json(text)
            if recovered:
                logger.info("JSON recovered from truncated response")
                if use_cache:
                    _cache_set(prompt, recovered)
                return recovered
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            return {
                "error":        "AI response was not valid JSON — please retry",
                "raw_response": text[:300],
            }

        except requests.exceptions.Timeout:
            logger.warning(f"NVIDIA API timeout on attempt {attempt + 1}")
            if attempt < retries:
                time.sleep(3)
                continue
            return {"error": "Request timed out — NVIDIA servers are busy. Please retry."}

        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response else 0
            if status_code == 429:
                wait = 5 * (attempt + 1)
                logger.warning(f"Rate limited — waiting {wait}s")
                if attempt < retries:
                    time.sleep(wait)
                    continue
                return {"error": "Rate limit reached — please wait a moment and retry"}
            if status_code >= 500:
                logger.error(f"NVIDIA API server error {status_code} on attempt {attempt + 1}")
                if attempt < retries:
                    time.sleep(3)
                    continue
            logger.error(f"NVIDIA API HTTP error {status_code}")
            return {"error": f"API error {status_code} — please retry"}

        except requests.exceptions.ConnectionError:
            logger.error("NVIDIA API connection error")
            if attempt < retries:
                time.sleep(2)
                continue
            return {"error": "Connection failed — check your internet connection"}

        except Exception as e:
            logger.error(f"Unexpected error calling NVIDIA API: {type(e).__name__}: {e}")
            return {"error": f"Unexpected error: {type(e).__name__}"}

    return {"error": "Failed after all retries — please try again"}


# ════════════════════════════════════════════════════════════════════
# VALIDATION
# ════════════════════════════════════════════════════════════════════

def _validate_hs(result: dict) -> dict:
    hs = str(result.get("hs_code", "")).strip()
    if not hs.isdigit() or len(hs) not in (6, 8):
        result["validation_warning"] = (
            f"HS code '{hs}' may be incorrect — ITC-HS codes are 8 digits. "
            "Verify at icegate.gov.in"
        )
    return result


# ════════════════════════════════════════════════════════════════════
# HS CLASSIFICATION
# ════════════════════════════════════════════════════════════════════

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


# ════════════════════════════════════════════════════════════════════
# IMPORT INTELLIGENCE
# ════════════════════════════════════════════════════════════════════

def get_import_details(product_description: str) -> dict:
    prompt = (
        "You are an Indian customs and tariff expert. "
        "Analyse this product being IMPORTED INTO INDIA (not US, not EU — INDIA ONLY).\n\n"
        f"{IMPORT_CONTEXT}\n\n"
        f"Product being imported into India: {product_description}\n\n"
        "CRITICAL RULES — failure to follow = wrong answer:\n"
        "1. BCD = India's Basic Customs Duty rate as per Indian Customs Tariff Act 2024\n"
        "2. India's agricultural BCD is HIGH (30-150%) — never give US/EU rates\n"
        "3. IGST must be EXACTLY one of: 5, 12, 18, or 28 (no decimals, no other values)\n"
        "4. SWS = always 10% of BCD (Social Welfare Surcharge)\n"
        "5. import_policy_status: exactly one of: Free, Restricted, or Prohibited\n"
        "6. hs_code: exactly 8 digits from ITC-HS 2022 Schedule\n\n"
        "Return ONLY this JSON (no markdown, no preamble):\n"
        "{\n"
        '  "hs_code": "8 digit ITC-HS 2022",\n'
        '  "product_description": "brief product description",\n'
        '  "basic_customs_duty_percent": "X% (India BCD)",\n'
        '  "social_welfare_surcharge_percent": "Y% (10% of BCD)",\n'
        '  "igst_percent": "Z% (5/12/18/28 only)",\n'
        '  "total_landed_cost_percent": "approx total effective import duty %",\n'
        '  "import_policy_status": "Free",\n'
        '  "license_required": false,\n'
        '  "scomet_applicable": false,\n'
        '  "special_conditions": "conditions or empty string",\n'
        '  "data_confidence": "high"\n'
        "}"
    )

    result = _call_llama(prompt)
    if "error" not in result:
        result = _validate_hs(result)
        igst = str(result.get("igst_percent", "")).replace("%", "").strip()
        if igst and igst not in ["5", "12", "18", "28"]:
            result["validation_warning"] = (
                f"IGST '{igst}%' is non-standard — Indian GST rates are 5/12/18/28%. Verify manually."
            )
    return result


# ════════════════════════════════════════════════════════════════════
# EXPORT INTELLIGENCE
# ════════════════════════════════════════════════════════════════════

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


# ════════════════════════════════════════════════════════════════════
# KNOWLEDGE MODE
# ════════════════════════════════════════════════════════════════════

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


# ════════════════════════════════════════════════════════════════════
# MASTER ENGINE
# ════════════════════════════════════════════════════════════════════

def trade_intelligence_engine(product_description: str, mode: str) -> dict:
    """Main entry point: route to appropriate analysis function."""
    if not product_description.strip():
        return {"error": "Product description cannot be empty"}

    # Input length guard
    if len(product_description) > 2000:
        product_description = product_description[:2000]
        logger.warning("Product description truncated to 2000 characters")

    dispatch = {
        "Import":    get_import_details,
        "Export":    get_export_details,
        "Knowledge": get_knowledge_details,
    }

    fn = dispatch.get(mode)
    if fn is None:
        return {"error": f"Invalid mode '{mode}'. Choose Import, Export, or Knowledge."}

    logger.info(f"Trade analysis requested: mode={mode}, product_length={len(product_description)}")
    return fn(product_description)


# ════════════════════════════════════════════════════════════════════
# TRADEGPT CHAT
# ════════════════════════════════════════════════════════════════════

def chat_with_tradegpt(messages: list, user_message: str) -> dict:
    """Multi-turn trade Q&A chat."""
    history = ""
    for m in messages[-6:]:  # last 3 exchanges
        role = "User" if m["role"] == "user" else "Assistant"
        history += f"{role}: {m['content']}\n"

    prompt = f"""You are TradeGPT, an expert on Indian import/export regulations, customs, GST, DGFT policy, and trade finance.

Conversation so far:
{history}
User: {user_message}

Answer helpfully and accurately. If you mention HS codes, duties, or regulations, be precise.
Return ONLY this JSON:
{{
  "reply": "your detailed answer here",
  "follow_up_questions": ["question 1?", "question 2?", "question 3?"],
  "relevant_links": ["https://icegate.gov.in", "https://dgft.gov.in"]
}}"""
    return _call_llama(prompt, max_tokens=1200)


# ════════════════════════════════════════════════════════════════════
# RISK ANALYZER
# ════════════════════════════════════════════════════════════════════

def analyze_trade_risk(
    product: str,
    origin_country: str,
    supplying_country: str,
    buyer_countries: str,
    direction: str = "Export",
    value_usd: str = "50,000",
) -> dict:
    """
    Comprehensive trade risk assessment with geopolitical context.
    origin_country  — where the product originates / is produced
    supplying_country — who is supplying (often same as origin, can differ)
    buyer_countries — destination / importing countries
    """
    prompt = (
        "You are a senior Indian trade risk analyst. "
        "Assess ALL risks for this trade deal using current 2024-2025 geopolitical knowledge.\n\n"
        f"Product: {product}\n"
        f"Origin Country (production): {origin_country}\n"
        f"Supplying Country (exporter): {supplying_country}\n"
        f"Buyer / Destination Countries: {buyer_countries}\n"
        f"Trade Direction (India perspective): {direction}\n"
        f"Deal Value: USD {value_usd}\n\n"
        "IMPORTANT — Consider ALL of the following for each risk category:\n"
        "- Current sanctions, trade embargoes, export controls (US/EU/UN)\n"
        "- Active geopolitical tensions (Russia-Ukraine, Israel-Gaza, China-Taiwan, India-Pakistan, Red Sea)\n"
        "- India FTA status with buyer/supplier countries\n"
        "- Currency volatility (USD/INR, relevant cross-rates)\n"
        "- Port/logistics disruptions (Suez Canal, Red Sea, specific ports)\n"
        "- Origin mismatch risk (product origin ≠ supplying country → anti-dumping, mislabelling)\n"
        "- Payment default risk (country credit rating, LC requirements)\n\n"
        "Return ONLY this JSON (no markdown, no preamble):\n"
        "{\n"
        '  "overall_risk_score": 65,\n'
        '  "risk_level": "Medium",\n'
        '  "executive_summary": "3 sentence summary covering key risks",\n'
        '  "geopolitical_alert": "specific current geopolitical concern or null",\n'
        '  "origin_supplying_mismatch_risk": "risk if origin≠supplier or null",\n'
        '  "risk_categories": [\n'
        '    {"category":"Regulatory & Sanctions","score":70,"level":"High","details":"explanation","mitigation":"how to mitigate"},\n'
        '    {"category":"Geopolitical Risk","score":65,"level":"Medium","details":"current events impact","mitigation":"steps"},\n'
        '    {"category":"Currency & Payment","score":45,"level":"Medium","details":"forex and payment risk","mitigation":"LC/hedging"},\n'
        '    {"category":"Logistics & Routing","score":55,"level":"Medium","details":"port/route risks","mitigation":"alternate routes"},\n'
        '    {"category":"Market & Demand","score":40,"level":"Low","details":"demand/price risk","mitigation":"strategy"},\n'
        '    {"category":"Compliance & Documentation","score":60,"level":"Medium","details":"certification/labelling risk","mitigation":"steps"}\n'
        '  ],\n'
        '  "key_recommendations": ["recommendation 1","recommendation 2","recommendation 3","recommendation 4"],\n'
        '  "payment_terms_advice": "recommended payment method (LC/DP/DA/advance)",\n'
        '  "insurance_suggestion": "insurance type and coverage advice",\n'
        '  "data_confidence": "high"\n'
        "}"
    )
    return _call_llama(prompt, max_tokens=2200)


# ════════════════════════════════════════════════════════════════════
# PRICE INTELLIGENCE
# ════════════════════════════════════════════════════════════════════

def get_price_intelligence(product: str, quantity: str, market: str) -> dict:
    """Global price benchmarking for a product."""
    prompt = f"""You are a global commodity and trade price analyst with expertise in Indian exports.

Product: {product}
Quantity: {quantity}
Target Market: {market}

Provide realistic price intelligence. Return ONLY this JSON:
{{
  "product": "{product}",
  "analysis_date": "2024",
  "fob_india_price_usd": "price per unit/MT",
  "cif_destination_usd": "estimated CIF price",
  "global_price_range_usd": "low - high per unit/MT",
  "india_competitiveness": "Strong / Moderate / Weak",
  "price_trend_6m": "Rising / Stable / Falling",
  "price_trend_details": "explanation of trend",
  "competitor_prices": [
    {{"country": "China", "price_usd": "X per MT", "quality_note": "note"}},
    {{"country": "Vietnam", "price_usd": "X per MT", "quality_note": "note"}},
    {{"country": "Thailand", "price_usd": "X per MT", "quality_note": "note"}}
  ],
  "margin_estimate_pct": "estimated profit margin %",
  "pricing_strategy": "recommended pricing approach",
  "key_price_drivers": ["driver 1", "driver 2", "driver 3"],
  "data_confidence": "medium"
}}"""
    return _call_llama(prompt, max_tokens=1500)


# ════════════════════════════════════════════════════════════════════
# COMPETITOR INTELLIGENCE
# ════════════════════════════════════════════════════════════════════

def get_competitor_intelligence(product: str, market: str) -> dict:
    """Competitive landscape analysis for Indian exporters."""
    prompt = f"""You are a trade intelligence analyst. Analyse the competitive landscape for Indian exporters.

Product: {product}
Target Market: {market}

Return ONLY this JSON:
{{
  "product": "{product}",
  "market": "{market}",
  "india_market_share_pct": "X%",
  "india_rank": "X of Y major exporters",
  "india_strengths": ["strength 1", "strength 2", "strength 3"],
  "india_weaknesses": ["weakness 1", "weakness 2"],
  "top_competitors": [
    {{
      "country": "China",
      "market_share_pct": "X%",
      "price_advantage": "cheaper/pricier by X%",
      "quality_position": "description",
      "india_advantage_over": "how India can beat them"
    }},
    {{
      "country": "Vietnam",
      "market_share_pct": "X%",
      "price_advantage": "cheaper/pricier by X%",
      "quality_position": "description",
      "india_advantage_over": "how India can beat them"
    }},
    {{
      "country": "Thailand",
      "market_share_pct": "X%",
      "price_advantage": "cheaper/pricier by X%",
      "quality_position": "description",
      "india_advantage_over": "how India can beat them"
    }}
  ],
  "market_entry_barriers": ["barrier 1", "barrier 2"],
  "differentiators": ["differentiator 1", "differentiator 2", "differentiator 3"],
  "recommended_strategy": "strategic recommendation",
  "data_confidence": "medium"
}}"""
    return _call_llama(prompt, max_tokens=2000)


# ════════════════════════════════════════════════════════════════════
# SMART TRADE IDEAS
# ════════════════════════════════════════════════════════════════════

def generate_smart_trade_ideas(profile: str, budget: str, direction: str, industry: str) -> dict:
    """
    Generate 5 tailored import/export business ideas.
    2 calls to avoid JSON truncation: Call1 → ideas 1-3, Call2 → ideas 4-5.
    """
    ctx = (f"Trader profile: {profile}. Budget: {budget}. "
           f"Trade direction: {direction}. Industry focus: {industry}.")

    def _idea_schema(rank: int) -> str:
        return (
            f'{{"rank":{rank},"title":"<name>","product":"<product>",'
            f'"hs_code_range":"HS Chapter XX",'
            f'"target_markets":["Country1","Country2"],'
            f'"initial_investment_inr":"X lakhs",'
            f'"monthly_revenue_potential_inr":"X lakhs",'
            f'"typical_margin_pct":"X-Y%",'
            f'"difficulty_level":"Easy",'
            f'"why_now":"<1 sentence>",'
            f'"india_advantage":"<1 sentence>",'
            f'"relevant_schemes":["RODTEP"],'
            f'"key_challenge":"<1 sentence>",'
            f'"first_step":"<1 sentence>"}}'
        )

    # ── Call 1: ideas 1-3 ────────────────────────────────────────
    prompt1 = (
        "You are a senior Indian trade consultant. "
        "Generate exactly 3 specific, actionable business ideas for this trader.\n\n"
        f"{ctx}\n\n"
        "Rules: Use real INR figures, fit within budget, focus on given industry, "
        "keep all text fields under 15 words.\n\n"
        "Return ONLY valid JSON — no markdown, no preamble:\n"
        "{\n"
        '  "profile_analysis": "<2-sentence assessment>",\n'
        '  "most_recommended": 1,\n'
        '  "ideas": [\n'
        f"    {_idea_schema(1)},\n"
        f"    {_idea_schema(2)},\n"
        f"    {_idea_schema(3)}\n"
        "  ]\n"
        "}"
    )

    result1 = _call_llama(prompt1, max_tokens=2200)
    if "error" in result1:
        # Fallback: try single-call with just 3 ideas
        logger.warning("Smart Trade Ideas call 1 failed, returning partial")
        return result1

    # ── Call 2: ideas 4-5 ────────────────────────────────────────
    prompt2 = (
        "You are a senior Indian trade consultant. "
        "Generate exactly 2 MORE business ideas (ideas 4 and 5 of a 5-idea set).\n\n"
        f"{ctx}\n\n"
        "Make these DIFFERENT from common ideas — niche products, value-added, tech-enabled.\n"
        "Rules: real INR figures, fit within budget, concise fields under 15 words.\n\n"
        "Return ONLY valid JSON — no markdown, no preamble:\n"
        "{\n"
        '  "ideas": [\n'
        f"    {_idea_schema(4)},\n"
        f"    {_idea_schema(5)}\n"
        "  ]\n"
        "}"
    )

    result2 = _call_llama(prompt2, max_tokens=1600)
    ideas2  = result2.get("ideas", []) if "error" not in result2 else []

    all_ideas = result1.get("ideas", []) + ideas2
    for i, idea in enumerate(all_ideas):
        idea["rank"] = i + 1

    return {
        "profile_analysis": result1.get("profile_analysis", ""),
        "most_recommended":  result1.get("most_recommended", 1),
        "ideas": all_ideas,
    }


def find_global_suppliers(product: str, quantity: str, quality: str, origin: str) -> dict:
    """Find global sourcing options for Indian importers."""
    origin_clause = f"Preferred origin: {origin}." if origin and origin.lower() != "any" else ""
    prompt = f"""You are a global sourcing expert for Indian importers. Find top supplier countries.

Product to Import: {product}
Quantity: {quantity}
Quality Standard: {quality}
{origin_clause}

Return ONLY this JSON:
{{
  "product": "{product}",
  "global_supply_overview": "2-sentence market overview",
  "recommended_origin": "best country to source from",
  "top_supply_origins": [
    {{
      "country": "Country Name",
      "fob_price_range_usd": "X-Y per unit/MT",
      "min_order_qty": "X units/MT",
      "lead_time_weeks": 4,
      "quality_level": "Premium/Standard/Budget",
      "bcd_pct": "X%",
      "igst_pct": "X%",
      "total_landed_markup_pct": "X%",
      "fta_with_india": true,
      "fta_saving": "X% duty saved",
      "concerns": ["concern 1"],
      "recommended_incoterm": "FOB/CIF/EXW"
    }},
    {{
      "country": "Country Name",
      "fob_price_range_usd": "X-Y per unit/MT",
      "min_order_qty": "X units/MT",
      "lead_time_weeks": 6,
      "quality_level": "Standard",
      "bcd_pct": "X%",
      "igst_pct": "X%",
      "total_landed_markup_pct": "X%",
      "fta_with_india": false,
      "fta_saving": null,
      "concerns": ["concern 1"],
      "recommended_incoterm": "FOB"
    }},
    {{
      "country": "Country Name",
      "fob_price_range_usd": "X-Y per unit/MT",
      "min_order_qty": "X units/MT",
      "lead_time_weeks": 8,
      "quality_level": "Budget",
      "bcd_pct": "X%",
      "igst_pct": "X%",
      "total_landed_markup_pct": "X%",
      "fta_with_india": false,
      "fta_saving": null,
      "concerns": ["concern 1", "concern 2"],
      "recommended_incoterm": "FOB"
    }}
  ],
  "verification_tips": ["tip 1", "tip 2", "tip 3"],
  "data_confidence": "medium"
}}"""
    return _call_llama(prompt, max_tokens=2500)


# ════════════════════════════════════════════════════════════════════
# AI TRADE REPORT
# ════════════════════════════════════════════════════════════════════

def generate_ai_trade_report(product: str, direction: str, countries: list) -> dict:
    """Generate a comprehensive trade opportunity report."""
    countries_str = ", ".join(countries) if countries else "Top 5 global markets"
    prompt = f"""You are a senior Indian trade consultant. Write a comprehensive trade report.

Product: {product}
Direction: {direction} (India perspective)
Target Countries: {countries_str}

Return ONLY this JSON:
{{
  "report_title": "Trade Opportunity Report: {product}",
  "executive_summary": "3-4 sentence overview",
  "market_opportunity_score": 72,
  "india_export_value_2023_usd": "approximate value",
  "global_market_size_usd": "approximate size",
  "growth_rate_pct": "X%",
  "target_markets": [
    {{
      "country": "Country",
      "market_size_usd": "size",
      "india_share_pct": "X%",
      "import_duty_on_india": "X%",
      "fta_benefit": "FTA benefit or none",
      "demand_trend": "Growing/Stable/Declining",
      "key_buyers": ["buyer type 1", "buyer type 2"],
      "entry_strategy": "recommended approach"
    }}
  ],
  "regulatory_snapshot": {{
    "hs_code": "XXXXXXXX",
    "export_policy": "Free/Restricted",
    "key_certifications": ["cert 1", "cert 2"],
    "documentation": ["doc 1", "doc 2", "doc 3"]
  }},
  "financial_projection": {{
    "estimated_fob_price_usd": "price",
    "container_load_value_usd": "value per 20ft container",
    "rodtep_benefit_pct": "X%",
    "estimated_net_margin_pct": "X-Y%"
  }},
  "action_plan": [
    {{"step": 1, "action": "action", "timeline": "Week 1-2", "authority": "DGFT/APEDA/etc"}},
    {{"step": 2, "action": "action", "timeline": "Week 3-4", "authority": "authority"}},
    {{"step": 3, "action": "action", "timeline": "Month 2", "authority": "authority"}},
    {{"step": 4, "action": "action", "timeline": "Month 3", "authority": "authority"}}
  ],
  "risks": ["risk 1", "risk 2", "risk 3"],
  "data_confidence": "medium"
}}"""
    return _call_llama(prompt, max_tokens=4000)


# ════════════════════════════════════════════════════════════════════
# DOCUMENT ANALYZER
# ════════════════════════════════════════════════════════════════════

def analyze_trade_document(document_text: str) -> dict:
    """Extract and analyze trade data from a document."""
    truncated = document_text[:3000]
    prompt = f"""You are an Indian trade document expert. Analyze this trade document.

Document Content:
{truncated}

Extract all relevant trade information. Return ONLY this JSON:
{{
  "document_type": "Invoice/Packing List/Bill of Lading/LC/Other",
  "parties": {{
    "exporter": "name or unknown",
    "importer": "name or unknown",
    "country_of_origin": "country or unknown",
    "destination_country": "country or unknown"
  }},
  "product_details": {{
    "description": "product description",
    "hs_code": "HS code if found or null",
    "quantity": "quantity if found",
    "unit_price": "price if found",
    "total_value": "total value if found",
    "currency": "currency code"
  }},
  "compliance_flags": ["flag 1 if any"],
  "missing_information": ["missing field 1", "missing field 2"],
  "recommendations": ["recommendation 1", "recommendation 2"],
  "risk_alerts": ["alert 1 if any"],
  "data_confidence": "high"
}}"""
    return _call_llama(prompt, max_tokens=1500)


# ════════════════════════════════════════════════════════════════════
# COMPLIANCE CHECKER
# ════════════════════════════════════════════════════════════════════

def check_trade_compliance(product: str, origin: str, destination: str, value_usd: float) -> dict:
    """Check trade compliance requirements for a shipment."""
    prompt = f"""You are an Indian trade compliance officer. Check compliance requirements.

Product: {product}
Origin: {origin}
Destination: {destination}
Shipment Value: USD {value_usd}

Return ONLY this JSON:
{{
  "compliance_status": "Clear/Review Required/Action Needed",
  "overall_score": 85,
  "checks": [
    {{"check": "Export License", "status": "Pass/Fail/Check", "details": "explanation"}},
    {{"check": "SCOMET Control", "status": "Pass/Fail/Check", "details": "explanation"}},
    {{"check": "Sanctions Screening", "status": "Pass/Fail/Check", "details": "explanation"}},
    {{"check": "Documentation", "status": "Pass/Fail/Check", "details": "explanation"}},
    {{"check": "FTA Eligibility", "status": "Pass/Fail/Check", "details": "explanation"}}
  ],
  "required_documents": ["document 1", "document 2", "document 3"],
  "duties_estimate": {{
    "bcd_pct": "X%",
    "igst_pct": "X%",
    "total_duty_usd": "approximate amount"
  }},
  "action_items": ["action 1", "action 2"],
  "data_confidence": "medium"
}}"""
    return _call_llama(prompt, max_tokens=1500)


# ════════════════════════════════════════════════════════════════════
# HEALTH CHECK
# ════════════════════════════════════════════════════════════════════

def health_check() -> dict:
    """Test connectivity to NVIDIA API. Returns status dict."""
    try:
        result = _call_llama(
            'Return ONLY this JSON: {"status":"ok","model":"llama-3.3-70b"}',
            retries=0,
            use_cache=False,
        )
        if "error" in result:
            return {"status": "error", "message": result["error"]}
        return {"status": "ok", "model": MODEL, "api_url": API_URL}
    except Exception as e:
        return {"status": "error", "message": str(e)}
"""
document_scanner.py
──────────────────────────────────────────────────────────────────────
Document Scanning Pipeline for Indian Trade Intelligence Engine
Supports: PDF, PNG, JPG, JPEG

Extraction strategies (in order):
  1. pdfplumber        — selectable-text PDFs + tables
  2. PyMuPDF text      — selectable-text fallback
  3. PyMuPDF blocks    — raw character extraction (embedded fonts)
  4. Render + OCR      — scanned PDFs (needs Tesseract binary)

Install Python libs:  pip install pdfplumber pymupdf pytesseract Pillow
Tesseract binary:
  Windows : https://github.com/UB-Mannheim/tesseract/wiki
  Ubuntu  : sudo apt-get install tesseract-ocr
  macOS   : brew install tesseract

Strategies 1-3 work WITHOUT Tesseract for native PDFs.
──────────────────────────────────────────────────────────────────────
"""

import io
import os
import re
import logging
import shutil
from pathlib import Path

logger = logging.getLogger("document_scanner")


def _configure_tesseract() -> bool:
    """
    Auto-detect and configure Tesseract binary path.
    Checks PATH first, then common installation directories.
    Returns True if Tesseract is found and configured.
    """
    try:
        import pytesseract

        # 1. Check if already on PATH
        if shutil.which("tesseract"):
            return True

        # 2. Check common Windows install paths
        win_paths = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.expanduser(r"~\AppData\Local\Tesseract-OCR\tesseract.exe"),
            r"C:\tools\Tesseract-OCR\tesseract.exe",
        ]
        for path in win_paths:
            if os.path.isfile(path):
                pytesseract.pytesseract.tesseract_cmd = path
                logger.info(f"Tesseract found at: {path}")
                return True

        # 3. Check common Linux/macOS paths
        unix_paths = [
            "/usr/bin/tesseract",
            "/usr/local/bin/tesseract",
            "/opt/homebrew/bin/tesseract",   # macOS Homebrew on Apple Silicon
            "/opt/local/bin/tesseract",       # macOS MacPorts
        ]
        for path in unix_paths:
            if os.path.isfile(path):
                pytesseract.pytesseract.tesseract_cmd = path
                logger.info(f"Tesseract found at: {path}")
                return True

        # 4. Check TESSERACT_CMD environment variable (set in .env file)
        env_path = os.environ.get("TESSERACT_CMD", "")
        if env_path and os.path.isfile(env_path):
            pytesseract.pytesseract.tesseract_cmd = env_path
            logger.info(f"Tesseract from TESSERACT_CMD env: {env_path}")
            return True

        # 5. Try loading from .env file directly (streamlit may not load it)
        try:
            env_file = Path(".env")
            if env_file.exists():
                for line in env_file.read_text().splitlines():
                    if line.startswith("TESSERACT_CMD="):
                        env_cmd = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if env_cmd and os.path.isfile(env_cmd):
                            pytesseract.pytesseract.tesseract_cmd = env_cmd
                            logger.info(f"Tesseract from .env file: {env_cmd}")
                            return True
        except Exception:
            pass

        logger.warning(
            "Tesseract binary not found. Install from https://github.com/UB-Mannheim/tesseract/wiki "
            "or set TESSERACT_CMD=<path> in your .env file"
        )
        return False

    except ImportError:
        return False


# Configure Tesseract at module import time
_TESSERACT_AVAILABLE = _configure_tesseract()

SUPPORTED_FORMATS = ["pdf", "png", "jpg", "jpeg"]


def _try_import(module_name: str):
    try:
        import importlib
        return importlib.import_module(module_name)
    except ImportError:
        return None


# ════════════════════════════════════════════════════════════════════
# TEXT CLEANING
# ════════════════════════════════════════════════════════════════════

def _clean_extracted_text(raw: str) -> str:
    if not raw:
        return ""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\f", "\n--- PAGE BREAK ---\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"(?<=\d)O(?=\d)", "0", text)
    text = text.replace("\x00", "")
    return text.strip()


# ════════════════════════════════════════════════════════════════════
# PDF STRATEGIES
# ════════════════════════════════════════════════════════════════════

def _strategy1_pdfplumber(file_bytes: bytes):
    pdfplumber = _try_import("pdfplumber")
    if not pdfplumber:
        raise ImportError("pdfplumber not installed")
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        pages = []
        for i, page in enumerate(pdf.pages):
            page_text = page.extract_text() or ""
            tables = page.extract_tables() or []
            table_text = ""
            for table in tables:
                for row in table:
                    if row:
                        row_clean = [str(c).strip() if c else "" for c in row]
                        table_text += "  |  ".join(row_clean) + "\n"
            combined = page_text
            if table_text and table_text not in page_text:
                combined = page_text + "\n" + table_text
            if combined.strip():
                pages.append(f"[Page {i+1}]\n{combined}")
        return "\n\n".join(pages), len(pdf.pages)


def _strategy2_pymupdf_text(file_bytes: bytes):
    fitz = _try_import("fitz")
    if not fitz:
        raise ImportError("PyMuPDF not installed")
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    pages = []
    for i, page in enumerate(doc):
        text = page.get_text("text")
        if text.strip():
            pages.append(f"[Page {i+1}]\n{text}")
    n = len(doc)
    doc.close()
    return "\n\n".join(pages), n


def _strategy3_pymupdf_blocks(file_bytes: bytes):
    fitz = _try_import("fitz")
    if not fitz:
        raise ImportError("PyMuPDF not installed")
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    pages = []
    for i, page in enumerate(doc):
        blocks = page.get_text("blocks")
        lines = [b[4].strip() for b in blocks if len(b) >= 5 and b[4].strip()]
        if lines:
            pages.append(f"[Page {i+1}]\n" + "\n".join(lines))
    n = len(doc)
    doc.close()
    return "\n\n".join(pages), n


def _strategy4_render_ocr(file_bytes: bytes, enhance: bool = True):
    # Ensure Tesseract is configured (re-check in case binary was added after startup)
    if not _TESSERACT_AVAILABLE:
        _configure_tesseract()

    fitz = _try_import("fitz")
    if not fitz:
        raise ImportError("PyMuPDF required for scanned PDF OCR")

    pytesseract = _try_import("pytesseract")
    if not pytesseract:
        raise ImportError(
            "pytesseract not installed. Run: pip install pytesseract\n"
            "Also install Tesseract binary:\n"
            "  Windows: https://github.com/UB-Mannheim/tesseract/wiki\n"
            "  Ubuntu:  sudo apt-get install tesseract-ocr"
        )

    try:
        pytesseract.get_tesseract_version()
    except Exception:
        raise RuntimeError(
            "Tesseract binary not found on your system.\n"
            "pip install pytesseract only installs the Python wrapper.\n"
            "You must also install the Tesseract engine:\n"
            "  Windows: https://github.com/UB-Mannheim/tesseract/wiki\n"
            "    (download .exe, install, add C:\\Program Files\\Tesseract-OCR\\ to PATH)\n"
            "  Ubuntu/WSL: sudo apt-get install tesseract-ocr\n"
            "  macOS: brew install tesseract\n"
            "Then restart your terminal and run: streamlit run app.py"
        )

    PIL_mod = _try_import("PIL.Image")
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    pages = []
    for i, page in enumerate(doc):
        mat = fitz.Matrix(3.0, 3.0)  # 216 DPI
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img_bytes = pix.tobytes("png")

        if PIL_mod and enhance:
            from PIL import Image as _PIL, ImageFilter, ImageEnhance
            img = _PIL.open(io.BytesIO(img_bytes)).convert("L")
            img = img.filter(ImageFilter.SHARPEN)
            img = ImageEnhance.Contrast(img).enhance(1.5)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            img_bytes = buf.getvalue()

        from PIL import Image as _PIL_raw
        text = pytesseract.image_to_string(
            _PIL_raw.open(io.BytesIO(img_bytes)),
            config="--oem 3 --psm 6",
            lang="eng",
        )
        if text.strip():
            pages.append(f"[Page {i+1}]\n{text}")

    n = len(doc)
    doc.close()
    return "\n\n".join(pages), n


def _extract_pdf(file_bytes: bytes, enhance: bool = True):
    errors = []

    for strategy_name, strategy_fn in [
        ("pdfplumber",    lambda: _strategy1_pdfplumber(file_bytes)),
        ("PyMuPDF text",  lambda: _strategy2_pymupdf_text(file_bytes)),
        ("PyMuPDF blocks",lambda: _strategy3_pymupdf_blocks(file_bytes)),
    ]:
        try:
            text, pages = strategy_fn()
            if len(text.strip()) > 50:
                logger.info(f"PDF extracted via {strategy_name}: {len(text)} chars, {pages} pages")
                return text, pages
            else:
                logger.debug(f"{strategy_name} returned <50 chars, trying next")
        except Exception as e:
            errors.append(f"{strategy_name}: {e}")
            logger.warning(f"{strategy_name} failed: {e}")

    # Strategy 4: OCR — raises RuntimeError with clear Tesseract message
    try:
        text, pages = _strategy4_render_ocr(file_bytes, enhance=enhance)
        if len(text.strip()) > 10:
            logger.info(f"PDF extracted via render+OCR: {len(text)} chars, {pages} pages")
            return text, pages
    except (RuntimeError, ImportError):
        raise  # Surface Tesseract error directly
    except Exception as e:
        errors.append(f"OCR: {e}")
        logger.warning(f"PDF OCR failed: {e}")

    raise RuntimeError(
        "All PDF extraction methods failed. "
        "Install: pip install pdfplumber pymupdf pytesseract | "
        + " | ".join(errors)
    )


# ════════════════════════════════════════════════════════════════════
# IMAGE EXTRACTION
# ════════════════════════════════════════════════════════════════════

def _extract_image(file_bytes: bytes, enhance: bool = True):
    pytesseract = _try_import("pytesseract")
    PIL_mod = _try_import("PIL.Image")

    if not pytesseract:
        raise ImportError("pytesseract not installed. Run: pip install pytesseract")
    if not PIL_mod:
        raise ImportError("Pillow not installed. Run: pip install Pillow")

    try:
        pytesseract.get_tesseract_version()
    except Exception:
        raise RuntimeError(
            "Tesseract binary not found.\n"
            "  Windows: https://github.com/UB-Mannheim/tesseract/wiki\n"
            "  Ubuntu:  sudo apt-get install tesseract-ocr"
        )

    from PIL import Image as _PIL, ImageFilter, ImageEnhance
    img = _PIL.open(io.BytesIO(file_bytes)).convert("RGB")

    if enhance:
        img = img.convert("L")
        w, h = img.size
        if w < 1000 or h < 1000:
            scale = max(1000 / w, 1000 / h, 1.0)
            img = img.resize((int(w * scale), int(h * scale)), _PIL.LANCZOS)
        img = img.filter(ImageFilter.SHARPEN)
        img = ImageEnhance.Contrast(img).enhance(1.8)
        img = ImageEnhance.Brightness(img).enhance(1.1)

    text = pytesseract.image_to_string(img, config="--oem 3 --psm 6", lang="eng")
    return text, 1


# ════════════════════════════════════════════════════════════════════
# PUBLIC API
# ════════════════════════════════════════════════════════════════════

TESSERACT_INSTALL_GUIDE = """
⚠️  Tesseract binary not found on your system.

pip install pytesseract  ← Python wrapper ONLY, does NOT install the OCR engine

INSTALL TESSERACT BINARY:

📥 Windows (most common fix):
   1. Download installer: https://github.com/UB-Mannheim/tesseract/wiki
      → Download: tesseract-ocr-w64-setup-5.x.x.exe
   2. During install: CHECK "Add to PATH" (important!)
   3. Default install path: C:\\Program Files\\Tesseract-OCR\\
   4. After install: CLOSE and REOPEN your terminal/PowerShell
   5. Verify: tesseract --version  (should show version number)
   6. If still not found: set env variable TESSERACT_CMD=C:\\Program Files\\Tesseract-OCR\\tesseract.exe

📥 Ubuntu / WSL:
   sudo apt-get update && sudo apt-get install -y tesseract-ocr
   sudo apt-get install -y tesseract-ocr-eng  (English language pack)

📥 macOS:
   brew install tesseract

After install: restart terminal → streamlit run app.py
"""


def scan_document(file_bytes: bytes, filename: str, enhance: bool = True,
                   force_ocr: bool = False) -> dict:
    """
    Scan and extract text from an uploaded document.

    Args:
      force_ocr: Skip text-layer extraction entirely and render pages as images
                 before OCR. Use for image-based PDFs where pdfplumber/PyMuPDF
                 return blank or garbled text.

    Returns dict:
      status       : "success" | "error"
      text         : extracted cleaned text
      char_count   : int
      pages        : int
      format       : "pdf" | "image"
      method       : extraction method used
      message      : error description if status == "error"
      install_hint : install instructions if dependency missing
    """
    if not file_bytes:
        return {"status": "error", "message": "No file data received.",
                "text": "", "char_count": 0, "pages": 0}

    ext = Path(filename).suffix.lower().lstrip(".")
    if ext not in SUPPORTED_FORMATS:
        return {"status": "error",
                "message": f"Unsupported format '.{ext}'. Supported: {', '.join(SUPPORTED_FORMATS)}",
                "text": "", "char_count": 0, "pages": 0}

    try:
        if ext == "pdf":
            if force_ocr:
                # Skip text extraction — go straight to render+OCR for image PDFs
                raw_text, num_pages = _strategy4_render_ocr(file_bytes, enhance=enhance)
                fmt, method = "pdf", "forced-ocr"
            else:
                raw_text, num_pages = _extract_pdf(file_bytes, enhance=enhance)
                fmt, method = "pdf", "pdf-extraction"
        else:
            raw_text, num_pages = _extract_image(file_bytes, enhance=enhance)
            fmt, method = "image", "ocr"

        clean_text = _clean_extracted_text(raw_text)

        if not clean_text.strip():
            return {"status": "error",
                    "message": "No text extracted. Document may be blank, encrypted, or too low quality.",
                    "text": "", "char_count": 0, "pages": num_pages,
                    "format": fmt, "method": method}

        return {"status": "success", "text": clean_text,
                "char_count": len(clean_text), "pages": num_pages,
                "format": fmt, "method": method, "message": ""}

    except RuntimeError as e:
        err = str(e)
        logger.error(f"Scan error '{filename}': {err}")
        is_tesseract = "Tesseract" in err or "tesseract" in err
        if is_tesseract:
            # Try one more time to auto-configure path
            if _configure_tesseract():
                try:
                    if ext == "pdf":
                        raw_text, num_pages = _strategy4_render_ocr(file_bytes, enhance=enhance)
                    else:
                        raw_text, num_pages = _extract_image(file_bytes, enhance=enhance)
                    clean_text = _clean_extracted_text(raw_text)
                    if clean_text.strip():
                        return {"status": "success", "text": clean_text,
                                "char_count": len(clean_text), "pages": num_pages,
                                "format": ext, "method": "ocr-retry", "message": ""}
                except Exception:
                    pass
        return {"status": "error", "message": err,
                "install_hint": TESSERACT_INSTALL_GUIDE if is_tesseract else None,
                "text": "", "char_count": 0, "pages": 0}

    except ImportError as e:
        missing = str(e)
        hints = {"pytesseract": "pip install pytesseract",
                 "pdfplumber":  "pip install pdfplumber",
                 "fitz":        "pip install pymupdf",
                 "Pillow":      "pip install Pillow"}
        hint = next((v for k, v in hints.items() if k in missing), f"pip install ...")
        logger.error(f"Missing lib: {missing}")
        return {"status": "error", "message": f"Library missing: {missing}",
                "install_hint": hint, "text": "", "char_count": 0, "pages": 0}

    except Exception as e:
        logger.error(f"Scan error '{filename}': {e}", exc_info=True)
        return {"status": "error", "message": f"Scanning failed: {e}",
                "text": "", "char_count": 0, "pages": 0}


def get_scanner_status() -> dict:
    """Return which scanning libraries and binaries are available."""
    pytesseract = _try_import("pytesseract")
    tesseract_binary = False
    tesseract_version = "not found"
    if pytesseract:
        try:
            tesseract_version = str(pytesseract.get_tesseract_version())
            tesseract_binary = True
        except Exception:
            pass

    return {
        "pdfplumber":        _try_import("pdfplumber") is not None,
        "pymupdf":           _try_import("fitz") is not None,
        "pytesseract_pkg":   pytesseract is not None,
        "tesseract_binary":  tesseract_binary,
        "tesseract_version": tesseract_version,
        "pillow":            _try_import("PIL") is not None,
        "supported_formats": SUPPORTED_FORMATS,
        "note": (
            "Strategies 1-3 (pdfplumber, PyMuPDF text, PyMuPDF blocks) work WITHOUT Tesseract "
            "for PDFs with a native text layer. "
            "Tesseract binary is only needed for fully scanned/image PDFs and image files."
        ),
    }