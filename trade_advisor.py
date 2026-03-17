"""
trade_advisor.py
🇮🇳 Advanced Trade Intelligence Modules — TradeGPT + 8 AI engines
"""
import json
from nvidia_service import _call_llama


# ─────────────────────────────────────────────────────────────
# 1. TRADEGPT CHAT
# ─────────────────────────────────────────────────────────────
def chat_with_tradegpt(user_message, conversation_history=None, context=None):
    ctx_block = ""
    if context:
        ctx_block = f"\n\nCurrent product context:\n{json.dumps(context, indent=2)}\n"
    history_text = ""
    for m in (conversation_history or [])[-6:]:
        role = "User" if m["role"] == "user" else "Assistant"
        history_text += f"{role}: {m['content']}\n"

    prompt = f"""You are TradeGPT — expert AI for Indian and global trade.
Knowledge: Customs Act, FTP 2023-28, ITC-HS 2022, BCD/IGST/SWS, anti-dumping,
RoDTEP/RoSCTL/AA/EPCG, DGFT, SCOMET, GST, trade finance (LC/DP/DA/ECGC/EXIM Bank),
Incoterms 2020, FTAs (ASEAN/UAE CEPA/Australia ECTA/Mauritius CECPA), ITC Trade Map.
{ctx_block}
Prior conversation:
{history_text}
User: {user_message}

Return ONLY JSON:
{{"reply":"detailed answer with \\n\\n for paragraphs","key_points":["bullet 1","bullet 2","bullet 3"],"verification_sources":["dgft.gov.in"],"follow_up_questions":["What is...?","How do I...?"]}}"""

    result = _call_llama(prompt)
    if "error" in result:
        return {"reply": f"Error: {result['error']}. Please retry.", "key_points": [], "verification_sources": [], "follow_up_questions": []}
    return {"reply": result.get("reply",""), "key_points": result.get("key_points",[]), "verification_sources": result.get("verification_sources",[]), "follow_up_questions": result.get("follow_up_questions",[])}


# ─────────────────────────────────────────────────────────────
# 2. TRADE RISK ANALYZER
# ─────────────────────────────────────────────────────────────
def analyze_trade_risk(
    product,
    origin_country="India",
    supplying_country="India",
    buyer_countries="",
    direction="Export",
    value_usd="50,000",
):
    prompt = (
        "You are a senior Indian trade risk analyst. "
        "Assess ALL risks for this trade deal using current 2024-2025 geopolitical knowledge.\n\n"
        f"Product: {product}\n"
        f"Origin Country (production): {origin_country}\n"
        f"Supplying Country (exporter): {supplying_country}\n"
        f"Buyer / Destination Countries: {buyer_countries}\n"
        f"Trade Direction (India perspective): {direction}\n"
        f"Deal Value: USD {value_usd}\n\n"
        "Consider: current sanctions, geopolitical tensions (Russia-Ukraine, Red Sea, India-Pakistan), "
        "India FTA status, currency volatility, port disruptions, origin mismatch risk, payment default risk.\n\n"
        "Return ONLY this JSON (no markdown, no preamble):\n"
        "{\n"
        '  "overall_risk_score": 65,\n'
        '  "risk_level": "Medium",\n'
        '  "executive_summary": "3 sentence summary",\n'
        '  "geopolitical_alert": "specific concern or null",\n'
        '  "origin_supplying_mismatch_risk": "risk description or null",\n'
        '  "risk_categories": [\n'
        '    {"category":"Regulatory & Sanctions","score":70,"level":"High","details":"explanation","mitigation":"steps"},\n'
        '    {"category":"Geopolitical Risk","score":65,"level":"Medium","details":"current events","mitigation":"steps"},\n'
        '    {"category":"Currency & Payment","score":45,"level":"Medium","details":"forex risk","mitigation":"LC/hedging"},\n'
        '    {"category":"Logistics & Routing","score":55,"level":"Medium","details":"port/route risk","mitigation":"alternate routes"},\n'
        '    {"category":"Market & Demand","score":40,"level":"Low","details":"demand risk","mitigation":"strategy"},\n'
        '    {"category":"Compliance & Documentation","score":60,"level":"Medium","details":"cert/labelling risk","mitigation":"steps"}\n'
        '  ],\n'
        '  "key_recommendations": ["rec 1","rec 2","rec 3","rec 4"],\n'
        '  "payment_terms_advice": "recommended payment method",\n'
        '  "insurance_suggestion": "insurance type and coverage",\n'
        '  "data_confidence": "high"\n'
        "}"
    )
    return _call_llama(prompt, max_tokens=2200)


# ─────────────────────────────────────────────────────────────
# 3. GLOBAL PRICE INTELLIGENCE
# ─────────────────────────────────────────────────────────────
def get_price_intelligence(product, quantity="1 MT", target_market="Global"):
    prompt = f"""Global price intelligence for: {product}
Quantity: {quantity}, Market: {target_market}. Use 2024 data.

Return ONLY JSON:
{{"product":"{product}","quantity_basis":"{quantity}","india_fob_price_usd":{{"min":0,"max":0,"typical":0,"unit":"USD/MT"}},"india_domestic_price_inr":{{"min":0,"max":0,"typical":0,"unit":"INR/MT"}},"target_market_landed_usd":{{"min":0,"max":0,"typical":0,"unit":"USD/MT"}},"gross_margin_pct":{{"min":0,"max":0}},"global_price_trend":"Rising","trend_reason":"specific reason","margin_potential":"High","margin_note":"explanation","competing_origins":["China","Vietnam"],"india_price_advantage":"India X% cheaper than main competitor","seasonal_pricing":"peak/off-peak pattern","freight_estimate_usd":{{"to_usa":0,"to_uae":0,"to_germany":0,"unit":"USD/MT"}},"price_drivers":["driver 1","driver 2","driver 3"],"data_confidence":"Medium","data_note":"Indicative — verify with live market quotes"}}"""
    return _call_llama(prompt)


# ─────────────────────────────────────────────────────────────
# 4. DOCUMENT ANALYZER
# ─────────────────────────────────────────────────────────────
def analyze_trade_document(document_text, doc_type="auto"):
    prompt = f"""Analyze this trade document. Type hint: {doc_type}

Document:
---
{document_text[:4000]}
---

Extract all fields. Validate HS codes (8 digits), dates, amounts. Flag issues.
Return ONLY JSON:
{{"document_type":"detected type","document_number":"or null","document_date":"DD/MM/YYYY","exporter":{{"name":"","address":"","iec_code":"","gstin":""}},"importer":{{"name":"","address":"","country":""}},"products":[{{"line_no":1,"description":"","hs_code":"","hs_code_valid":true,"quantity":"","unit":"","unit_price_usd":0,"total_value_usd":0}}],"total_invoice_value":{{"amount":0,"currency":"USD"}},"incoterm":"","port_of_loading":"","port_of_discharge":"","vessel_or_flight":"","bl_or_awb_number":"","country_of_origin":"","country_of_destination":"","payment_terms":"","flags":["anomaly 1"],"missing_critical_fields":["missing field 1"],"compliance_status":"OK","compliance_notes":"observations"}}"""
    result = _call_llama(prompt)
    if "error" not in result:
        result["_analyzed"] = True
        for p in result.get("products", []):
            hs = str(p.get("hs_code","")).strip()
            p["hs_code_valid"] = bool(hs and hs.isdigit() and len(hs) in (6,8))
    return result


# ─────────────────────────────────────────────────────────────
# 5. TRADE COMPLIANCE CHECKER
# ─────────────────────────────────────────────────────────────
def check_trade_compliance(product, hs_code, origin_country, destination_country, direction="Export"):
    prompt = f"""Indian trade compliance check:
Product: {product}, HS: {hs_code}, Direction: {direction}
Origin: {origin_country}, Destination: {destination_country}

Return ONLY JSON:
{{"product":"{product}","hs_code":"{hs_code}","direction":"{direction}","overall_compliance_status":"CLEAR","compliance_summary":"one-sentence summary","checks":{{"scomet_control":{{"status":"CLEAR","detail":"not a controlled item"}},"dgft_policy":{{"status":"CLEAR","detail":"Free category FTP 2023-28"}},"un_sanctions":{{"status":"CLEAR","detail":"no sanctions applicable"}},"prohibited_items":{{"status":"CLEAR","detail":"not on prohibited list"}},"licence_required":{{"status":"NOT REQUIRED","detail":"no licence needed"}},"quality_standards":{{"status":"CHECK","detail":"verify BIS/FSSAI if applicable"}}}},"required_documents":["Commercial Invoice","Packing List","Certificate of Origin","Shipping Bill"],"optional_documents":["Health Certificate if food","Fumigation Certificate"],"certifications_needed":["BIS/FSSAI/APEDA if applicable"],"blocked_reason":null,"conditional_requirements":[],"recommended_next_steps":["Step 1","Step 2"],"authority_contacts":{{"dgft":"1800-111-550 / dgft.gov.in","customs":"icegate.gov.in","scomet":"scomet@dgft.gov.in"}},"estimated_time":"3-7 working days","estimated_cost":"INR 5,000-25,000 standard documentation"}}"""
    return _call_llama(prompt)


# ─────────────────────────────────────────────────────────────
# 6. COMPETITOR INTELLIGENCE
# ─────────────────────────────────────────────────────────────
def get_competitor_intelligence(product, target_market):
    prompt = f"""India's global competition for: {product} in {target_market}.
Base on ITC Trade Map / UN Comtrade patterns.

Return ONLY JSON:
{{"product":"{product}","target_market":"{target_market}","india_market_share_pct":0.0,"india_rank":0,"market_total_imports_usd_m":0,"top_competitors":[{{"country":"China","share_pct":35.0,"rank":1,"price_level":"Lowest","india_vs_competitor":"India advantage","strengths":["factor1","factor2"]}}],"india_strengths":["advantage 1","advantage 2"],"india_weaknesses":["gap 1","gap 2"],"differentiation_strategy":"specific strategy","price_competitiveness":"India X% vs average competitor","quality_positioning":"positioning statement","market_entry_difficulty":"Medium","fta_advantage":"FTA detail or MFN","certification_barriers":["ISO 9001","CE Mark if applicable"],"growth_opportunity":"specific 12-24 month opportunity","recommended_buyer_types":["type 1","type 2"],"b2b_platforms":["Alibaba","TradeIndia","IndiaMart"]}}"""
    return _call_llama(prompt)


# ─────────────────────────────────────────────────────────────
# 7. SMART TRADE IDEAS
# ─────────────────────────────────────────────────────────────
def generate_smart_trade_ideas(user_profile, budget_inr="10-50 lakhs", direction="Export", industry_focus="Any"):
    prompt = f"""5 specific Indian trade business ideas for:
Profile: {user_profile}, Budget: {budget_inr} INR, Direction: {direction}, Focus: {industry_focus}

Prioritize currently trending opportunities with India's genuine competitive advantage.
Return ONLY JSON:
{{"profile_analysis":"honest assessment","ideas":[{{"rank":1,"title":"specific title","product":"specific product+spec","hs_code_range":"0910","direction":"Export","target_markets":["UAE","USA"],"why_now":"current market driver","india_advantage":"concrete reason India wins","typical_margin_pct":"18-24%","initial_investment_inr":"15-20 lakhs","monthly_revenue_potential_inr":"8-15 lakhs","key_challenge":"#1 real challenge","first_step":"specific first action","relevant_schemes":["RoDTEP","EPCG"],"difficulty_level":"Beginner","months_to_first_shipment":"4-6","iec_needed":true}}],"quick_wins":["90-day opportunity 1","opportunity 2","opportunity 3"],"avoid_these":["oversaturated idea 1","trap 2"],"market_trends":["trend 1","trend 2","trend 3"],"most_recommended":1,"first_week_actions":["Day 1: Register IEC / check eligibility","Day 2-3: Research top 5 buyers on Alibaba/TradeIndia","Day 4-7: Contact 3 freight forwarders for rate quotes"]}}"""
    return _call_llama(prompt)


# ─────────────────────────────────────────────────────────────
# 8. SUPPLIER CHAIN FINDER
# ─────────────────────────────────────────────────────────────
def find_global_suppliers(product, quantity_required, quality_standard="Standard", preferred_origin="Any"):
    prompt = f"""Global supplier intelligence for importing to India:
Product: {product}, Qty: {quantity_required}, Quality: {quality_standard}, Origin pref: {preferred_origin}

Return ONLY JSON:
{{"product":"{product}","global_supply_overview":"2-sentence overview","total_india_import_usd_m":0,"top_supply_origins":[{{"country":"China","rank":1,"why_recommended":"largest producer","fob_price_range_usd":"X-Y /MT","quality_level":"High","min_order_qty":"1 MT","lead_time_weeks":"6-8","bcd_pct":"10%","igst_pct":"18%","total_landed_markup_pct":"~42%","fta_with_india":false,"fta_saving":"N/A","concerns":["quality consistency"],"b2b_platforms":["Alibaba","Global Sources"]}}],"india_domestic_alternative":{{"available":true,"producing_states":["Gujarat","Maharashtra"],"domestic_vs_import":"domestic X% cheaper including duties","recommendation":"import or domestic + why"}},"recommended_strategy":"specific approach","due_diligence_steps":["Get ISO cert","Order sample first","Verify Trade Assurance","Check Indian Embassy trade section"],"payment_advice":"LC first order, DP after 2 shipments","total_landed_cost_breakdown":{{"fob":"100%","freight_cif":"+12-15%","bcd":"+10%","sws":"+1%","igst":"+18% (recoverable)","clearing":"+1-2%","total":"~142-146% of FOB"}},"trade_finance_options":["SBI Trade Finance","EXIM Bank import credit"]}}"""
    return _call_llama(prompt, max_tokens=3000)


# ─────────────────────────────────────────────────────────────
# 9. AI TRADE REPORT GENERATOR
# ─────────────────────────────────────────────────────────────
def generate_ai_trade_report(product, direction, target_countries):
    countries_str = ", ".join(target_countries[:5])
    prompt = f"""Comprehensive trade intelligence report:
Product: {product}, Direction: {direction} from/to India, Markets: {countries_str}

Return ONLY JSON:
{{"report_title":"Trade Intelligence Report: {product}","executive_summary":{{"headline_finding":"most important insight","market_opportunity":"quantified opportunity","india_readiness":"High - reason","top_recommendation":"primary action","key_risks":["risk 1","risk 2"]}},"product_profile":{{"hs_code":"8-digit","global_market_size_usd_b":0,"growth_rate_pct":0,"india_export_value_usd_m":0,"india_global_rank":0,"product_type":"Commodity"}},"market_analysis":[{{"country":"","import_size_usd_m":0,"india_share_pct":0,"growth_rate_pct":0,"opportunity_score":0,"entry_difficulty":"Medium","tariff_pct":0,"fta_benefit":"N/A","recommendation":"Priority Entry"}}],"regulatory_analysis":{{"hs_code":"","export_policy":"Free","import_policy":"Free","licence_required":false,"key_documents":[],"certifications":[],"compliance_complexity":"Low","compliance_time_days":7}},"pricing_analysis":{{"india_fob_range":"","gross_margin_range_pct":"","price_trend":"Rising","india_price_position":"competitive"}},"competitive_analysis":{{"india_rank":0,"top_competitors":[],"india_advantages":[],"india_gaps":[],"win_strategy":""}},"risk_summary":{{"overall":"Medium","top_risks":[],"mitigation":[]}},"action_plan":[{{"week":"1-2","action":"","output":""}},{{"week":"3-4","action":"","output":""}},{{"week":"5-8","action":"","output":""}},{{"week":"9-12","action":"","output":""}}],"useful_resources":[{{"name":"DGFT","url":"dgft.gov.in","purpose":"Policy and licences"}},{{"name":"ICEGATE","url":"icegate.gov.in","purpose":"HS codes and customs"}},{{"name":"ITC Trade Map","url":"trademap.org","purpose":"Global statistics"}}],"disclaimer":"AI-generated — verify with official sources before business decisions."}}"""
    return _call_llama(prompt, max_tokens=3000)
