"""The fixed configuration a new desk starts with: the seller, team, personas, segments, settings, sources and the
profile versions the demo opens with. The seller is Lumen Ledger, the same invented company Account Desk sells for."""
from __future__ import annotations

SELLER = "Lumen Ledger"

PROFILE_INDUSTRIES = ["Software", "Fintech", "Data infrastructure", "Developer tools", "Marketplaces"]
OTHER_INDUSTRIES = ["Healthcare software", "IT services", "Agencies", "E-commerce", "Manufacturing", "Education",
                    "Government", "Media", "Logistics"]
INDUSTRIES = PROFILE_INDUSTRIES + OTHER_INDUSTRIES
PRICING = ["usage", "seat", "transaction", "mixed"]
PRICING_LABEL = {"usage": "Usage-based", "seat": "Per seat", "transaction": "Per transaction", "mixed": "Mixed",
                 "unknown": "Unknown"}
REVENUE_BANDS = ["<$5M", "$5M-$20M", "$20M-$100M", "$100M-$500M", "$500M+"]
SIZE_BANDS = [("20 to 119", 20, 119), ("120 to 499", 120, 499), ("500 to 1,999", 500, 1999),
              ("2,000 to 4,999", 2000, 4999), ("5,000+", 5000, 10_000_000)]
TECH = ["Salesforce", "Snowflake", "NetSuite", "Stripe", "HubSpot", "BigQuery", "QuickBooks", "Zuora", "Chargebee",
        "Databricks", "SAP", "Legacy on-prem ERP"]
COMPETITORS = ["Meterly", "Billform", "Chargewell", "Ledgerline", "Quotient Billing"]
LOSS_CODES = ["price", "timing", "no_decision", "competitor", "missing_feature", "compliance", "champion_left",
              "bad_fit", "other"]
LOSS_LABEL = {"price": "Price", "timing": "Timing", "no_decision": "No decision", "competitor": "Competitor",
              "missing_feature": "Missing feature", "compliance": "Compliance", "champion_left": "Champion left",
              "bad_fit": "Bad fit", "other": "Other"}
REGION_GROUPS = {
    "North America": ("North America", ["US", "CA", "MX"]),
    "UK and Ireland": ("Europe", ["GB", "IE"]),
    "DACH": ("Europe", ["DE", "AT", "CH"]),
    "France and Benelux": ("Europe", ["FR", "NL", "BE"]),
    "Nordics": ("Europe", ["SE", "DK", "NO", "FI"]),
    "Southern Europe": ("Europe", ["ES", "IT", "PT"]),
    "Latin America": ("Latin America", ["BR", "AR"]),
    "Asia Pacific": ("Asia Pacific", ["AU", "IN", "SG"]),
}
SERVED_REGIONS = ["North America", "Europe"]
COUNTRY_NAME = {"US": "United States", "CA": "Canada", "GB": "United Kingdom", "IE": "Ireland", "DE": "Germany",
                "AT": "Austria", "CH": "Switzerland", "FR": "France", "NL": "Netherlands", "BE": "Belgium",
                "SE": "Sweden", "DK": "Denmark", "NO": "Norway", "FI": "Finland", "ES": "Spain", "IT": "Italy",
                "PT": "Portugal", "BR": "Brazil", "MX": "Mexico", "AR": "Argentina", "AU": "Australia", "IN": "India", "SG": "Singapore"}

USERS = [
    # name, email, role, timezone, started_on, selling hours a month for account work
    ("Sam Kowalski", "sam.kowalski@lumenledger.example", "revops", "America/New_York", "2023-02-01", 0),
    ("Elena Duarte", "elena.duarte@lumenledger.example", "manager", "America/New_York", "2022-09-12", 0),
    ("Maya Okafor", "maya.okafor@lumenledger.example", "sdr", "America/New_York", "2025-03-03", 100),
    ("Daniel Reyes", "daniel.reyes@lumenledger.example", "sdr", "America/Chicago", "2024-08-19", 100),
    ("Priya Natarajan", "priya.natarajan@lumenledger.example", "sdr", "Europe/London", "2024-01-08", 100),
    ("Tom Whitaker", "tom.whitaker@lumenledger.example", "sdr", "America/Los_Angeles", "2025-06-02", 100),
    ("Nadia Haddad", "nadia.haddad@lumenledger.example", "sdr", "Europe/Berlin", "2026-12-01", 100),
    ("Grace Lindqvist", "grace.lindqvist@lumenledger.example", "ae", "America/New_York", "2023-05-15", 40),
    ("Omar Bello", "omar.bello@lumenledger.example", "ae", "America/Chicago", "2024-02-05", 40),
    ("Hannah Mercer", "hannah.mercer@lumenledger.example", "ae", "Europe/London", "2023-11-06", 40),
]

PERSONAS = {
    "cfo": "Finance leader", "controller": "Controller", "revops": "Revenue operations", "data": "Data and systems",
    "procurement": "Procurement", "security": "Security", "ceo": "Chief executive",
}

SETTINGS = {
    "evidence_window_months": (24, "Our default: deals closed in the last two years."),
    "min_opps": (30, "Our default: fewer opportunities than this is too few to tell."),
    "min_wins": (5, "Our default: fewer wins than this is too few to tell."),
    "family_alpha": (0.05, "Our default for the corrected test across every trait value."),
    "shrink_k": (20, "Our default: a segment's win rate is pulled toward the overall rate as if it had 20 more deals at it."),
    "hours_per_tier": ({"A": 1.0, "B": 0.4, "C": 0.1, "X": 0}, "Our assumption, not an industry figure: hours a month one account needs while it is worked, with Account Desk doing research and drafting."),
    "account_cycle_months": (3, "Our assumption: an account is worked for one quarter, so a seat works four books of accounts a year."),
    "balance_band": (0.15, "Our default: each person's expected value within this share of the territory mean."),
    "held_back_share": (0.2, "Same as Account Desk: one in five accounts in a segment test is held back."),
    "drop_rule_min_opps": (60, "Our default: a rule is proposed for removal only with this many opportunities behind it."),
}

# The segments every profile version in the demo carries. First match wins; the rest is Outside.
CORE = (120, 1999)
SEGMENTS = [
    {"key": "fintech_core", "label": "Fintech, 120 to 499", "when": [
        {"field": "industry", "op": "in", "value": ["Fintech"]}, {"field": "employees", "op": "between", "value": [120, 499]}]},
    {"key": "fintech_large", "label": "Fintech, 500 to 1,999", "when": [
        {"field": "industry", "op": "in", "value": ["Fintech"]}, {"field": "employees", "op": "between", "value": [500, 1999]}]},
    {"key": "software", "label": "Software", "when": [
        {"field": "industry", "op": "in", "value": ["Software"]}, {"field": "employees", "op": "between", "value": list(CORE)}]},
    {"key": "data_infra", "label": "Data infrastructure", "when": [
        {"field": "industry", "op": "in", "value": ["Data infrastructure"]}, {"field": "employees", "op": "between", "value": list(CORE)}]},
    {"key": "devtools", "label": "Developer tools", "when": [
        {"field": "industry", "op": "in", "value": ["Developer tools"]}, {"field": "employees", "op": "between", "value": list(CORE)}]},
    {"key": "marketplaces", "label": "Marketplaces", "when": [
        {"field": "industry", "op": "in", "value": ["Marketplaces"]}, {"field": "employees", "op": "between", "value": list(CORE)}]},
    {"key": "enterprise", "label": "Enterprise", "when": [
        {"field": "industry", "op": "in", "value": PROFILE_INDUSTRIES}, {"field": "employees", "op": "between", "value": [2000, 10_000_000]}]},
    {"key": "small", "label": "Small", "when": [
        {"field": "industry", "op": "in", "value": PROFILE_INDUSTRIES}, {"field": "employees", "op": "between", "value": [20, 119]}]},
]
OUTSIDE = {"key": "outside", "label": "Outside the profile"}
SEGMENT_LABEL = {s["key"]: s["label"] for s in SEGMENTS} | {OUTSIDE["key"]: OUTSIDE["label"]}

# Account Desk's published ICP (its src/outbound/seed/catalog.py ICP), carried here as profile v3.
AD_ICP = {
    "factors": [
        {"key": "industry", "field": "industry", "op": "in",
         "value": ["Software", "Fintech", "Data infrastructure", "Developer tools", "Marketplaces"], "weight": 30},
        {"key": "size", "field": "employees", "op": "between", "value": [120, 2000], "weight": 25},
        {"key": "region", "field": "region", "op": "in", "value": ["North America", "Europe"], "weight": 15},
        {"key": "revenue", "field": "revenue_band", "op": "in", "value": ["$20M-$100M", "$100M-$500M"], "weight": 15},
        {"key": "stack", "field": "tech", "op": "has_any", "value": ["Snowflake", "NetSuite", "Salesforce", "Stripe"],
         "weight": 15},
    ],
    "penalties": [
        {"key": "legacy_erp", "field": "tech", "op": "has_any", "value": ["Legacy on-prem ERP"], "weight": 20},
    ],
    "excludes": [
        {"key": "sector", "field": "industry", "op": "in", "value": ["Government", "Education"], "reason": "Sector we do not sell to"},
        {"key": "too_small", "field": "employees", "op": "between", "value": [0, 19], "reason": "Too small to need us"},
    ],
    "tiers": {"A": 85, "B": 65},
}

FIELD_LABEL = {"industry": "Industry", "employees": "Employees", "region": "Region", "revenue_band": "Revenue",
               "tech": "Technology", "pricing_model": "Pricing model", "country": "Country", "source": "Deal source",
               "hq_city": "HQ city", "founded": "Founded", "segment": "Segment", "size_band": "Employees",
               "region_group": "Region group"}

# Fields Account Desk's ICP and accounts file can carry (its SPEC 22.7 and examples/accounts.example.csv).
AD_FIELDS = {"industry", "employees", "region", "revenue_band", "tech"}
AD_COLUMNS = ["name", "domain", "industry", "employees", "country", "revenue_band", "tech", "lifecycle", "owner_email",
              "crm_id", "parent_domain"]


def size_band(employees: int | None) -> str | None:
    if employees is None:
        return None
    for label, lo, hi in SIZE_BANDS:
        if lo <= employees <= hi:
            return label
    return None


def founded_band(year: int | None) -> str | None:
    if year is None:
        return None
    if year < 2000:
        return "Before 2000"
    if year < 2010:
        return "2000 to 2009"
    if year < 2015:
        return "2010 to 2014"
    if year < 2020:
        return "2015 to 2019"
    return "2020 on"
