"""
Raffles Health Insurance / Bupa Global
Worldwide Health Options (WHo) Rate Engine
FastAPI — data baked in, no database required
"""
import os
import logging
from typing import Optional
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from rates_data import (
    RATES,
    COUNTRY_ZONE_MAP,
    ZONES_WITH_FULL_DATA,
    DEDUCTIBLES,
    CURRENCY,
    EFFECTIVE_DATE,
    INSURER,
    ADMINISTRATOR,
    PRODUCT,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_KEY = os.environ.get("API_KEY", "bupa-worldwide-health-Mo-2026-secret")

app = FastAPI(
    title="Raffles-Bupa WHo Rate Engine",
    description="Worldwide Health Options subscription rates — USD, from 1 April 2025",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Auth ──────────────────────────────────────────────────────────────────────

def require_api_key(x_api_key: str = Header(...)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


# ── Helpers ───────────────────────────────────────────────────────────────────

def resolve_zone(country: str, include_us: bool) -> str:
    """Return the correct zone key given country + US coverage flag."""
    base_zone = COUNTRY_ZONE_MAP.get(country)
    if not base_zone:
        raise HTTPException(status_code=404, detail=f"Country not found: {country}")
    if include_us:
        us_zone = base_zone + "_us"
        if us_zone in RATES:
            return us_zone
        # zone1 already includes US — no _us variant
        return base_zone
    return base_zone


def normalise_age(age: int) -> str:
    """Map integer age to the rate table key."""
    if age < 0:
        raise HTTPException(status_code=400, detail="Age must be >= 0")
    if age <= 15:
        return "0-15"
    if age >= 82:
        return "82+"
    return str(age)


def get_rate(zone: str, deductible: str, age_key: str):
    if zone not in RATES:
        raise HTTPException(status_code=404, detail=f"Zone not found: {zone}")
    if deductible not in RATES[zone]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid deductible: {deductible}. Valid: {DEDUCTIBLES}",
        )
    if age_key not in RATES[zone][deductible]:
        raise HTTPException(status_code=400, detail=f"Age key not found: {age_key}")
    monthly, annual = RATES[zone][deductible][age_key]
    return {"monthly": monthly, "annual": annual}


# ── Request / Response models ─────────────────────────────────────────────────

class QuoteRequest(BaseModel):
    country: str
    age: int
    deductible: str = "0"          # "0","425","850","1700","3400","8500"
    include_us: bool = False        # True = include USA coverage
    payment_frequency: str = "monthly"  # "monthly" or "annual"


class QuoteByZoneRequest(BaseModel):
    zone: str                       # e.g. "zone6", "zone6_us"
    age: int
    deductible: str = "0"
    payment_frequency: str = "monthly"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status": "ok",
        "product": PRODUCT,
        "insurer": INSURER,
        "administrator": ADMINISTRATOR,
        "currency": CURRENCY,
        "effective_date": EFFECTIVE_DATE,
        "zones_loaded": len(RATES),
    }


@app.get("/zones")
def list_zones(x_api_key: str = Header(...)):
    require_api_key(x_api_key)
    return {
        "zones": ZONES_WITH_FULL_DATA,
        "deductibles": DEDUCTIBLES,
        "currency": CURRENCY,
    }


@app.get("/countries")
def list_countries(x_api_key: str = Header(...)):
    require_api_key(x_api_key)
    return {"countries": sorted(COUNTRY_ZONE_MAP.keys())}


@app.get("/country/{country}/zone")
def country_zone(country: str, x_api_key: str = Header(...)):
    require_api_key(x_api_key)
    zone = COUNTRY_ZONE_MAP.get(country)
    if not zone:
        raise HTTPException(status_code=404, detail=f"Country not found: {country}")
    return {"country": country, "zone": zone, "zone_with_us": zone + "_us" if zone + "_us" in RATES else zone}


@app.post("/quote")
def quote(req: QuoteRequest, x_api_key: str = Header(...)):
    """
    Get a premium for a specific country, age and deductible.
    Set include_us=true for plans that cover treatment in the USA.
    """
    require_api_key(x_api_key)

    if req.deductible not in DEDUCTIBLES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid deductible '{req.deductible}'. Valid: {DEDUCTIBLES}",
        )

    zone = resolve_zone(req.country, req.include_us)
    age_key = normalise_age(req.age)
    rate = get_rate(zone, req.deductible, age_key)

    premium = rate["monthly"] if req.payment_frequency == "monthly" else rate["annual"]

    return {
        "country": req.country,
        "zone": zone,
        "age": req.age,
        "age_band": age_key,
        "deductible_usd": req.deductible,
        "include_us": req.include_us,
        "currency": CURRENCY,
        "payment_frequency": req.payment_frequency,
        "premium": premium,
        "monthly": rate["monthly"],
        "annual": rate["annual"],
        "effective_date": EFFECTIVE_DATE,
        "insurer": INSURER,
        "product": PRODUCT,
    }


@app.post("/quote/zone")
def quote_by_zone(req: QuoteByZoneRequest, x_api_key: str = Header(...)):
    """
    Get a premium by zone directly (bypasses country lookup).
    """
    require_api_key(x_api_key)

    if req.deductible not in DEDUCTIBLES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid deductible '{req.deductible}'. Valid: {DEDUCTIBLES}",
        )

    age_key = normalise_age(req.age)
    rate = get_rate(req.zone, req.deductible, age_key)

    premium = rate["monthly"] if req.payment_frequency == "monthly" else rate["annual"]

    return {
        "zone": req.zone,
        "age": req.age,
        "age_band": age_key,
        "deductible_usd": req.deductible,
        "currency": CURRENCY,
        "payment_frequency": req.payment_frequency,
        "premium": premium,
        "monthly": rate["monthly"],
        "annual": rate["annual"],
        "effective_date": EFFECTIVE_DATE,
        "insurer": INSURER,
        "product": PRODUCT,
    }


@app.get("/quote/all-deductibles")
def quote_all_deductibles(
    country: str,
    age: int,
    include_us: bool = False,
    x_api_key: str = Header(...),
):
    """
    Return premiums for all deductible options for a country/age.
    Useful for building a comparison table in the UI.
    """
    require_api_key(x_api_key)
    zone = resolve_zone(country, include_us)
    age_key = normalise_age(age)

    results = []
    for ded in DEDUCTIBLES:
        rate = get_rate(zone, ded, age_key)
        results.append({
            "deductible_usd": ded,
            "monthly": rate["monthly"],
            "annual": rate["annual"],
        })

    return {
        "country": country,
        "zone": zone,
        "age": age,
        "age_band": age_key,
        "include_us": include_us,
        "currency": CURRENCY,
        "effective_date": EFFECTIVE_DATE,
        "insurer": INSURER,
        "product": PRODUCT,
        "rates": results,
    }


@app.get("/deductibles")
def list_deductibles(x_api_key: str = Header(...)):
    require_api_key(x_api_key)
    return {"deductibles_usd": DEDUCTIBLES}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
