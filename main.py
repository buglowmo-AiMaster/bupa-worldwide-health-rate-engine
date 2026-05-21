"""
Raffles Health Insurance / Bupa Global
Worldwide Health Options (WHo) Rate Engine
FastAPI — PostgreSQL-backed (migrated from file-based)
"""
import os
import json
import logging
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import execute_values, RealDictCursor

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

DATABASE_URL = os.environ["DATABASE_URL"]
API_KEY      = os.environ["API_KEY"]
SETUP_KEY    = os.environ.get("SETUP_KEY", "bupa-setup-secret")

app = FastAPI(
    title="Raffles-Bupa WHo Rate Engine",
    description="Worldwide Health Options subscription rates — USD, from 1 April 2025",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── DB connection ─────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(DATABASE_URL)


# ── Auth ──────────────────────────────────────────────────────

def require_api_key(x_api_key: str = Header(...)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

def require_setup_key(x_setup_key: str = Header(...)):
    if x_setup_key != SETUP_KEY:
        raise HTTPException(status_code=401, detail="Invalid setup key")

def require_admin_key(x_admin_key: str = Header(...)):
    if x_admin_key != SETUP_KEY:
        raise HTTPException(status_code=401, detail="Invalid admin key")


# ── Helpers ───────────────────────────────────────────────────

def normalise_age(age: int) -> str:
    if age < 0:
        raise HTTPException(status_code=400, detail="Age must be >= 0")
    if age <= 15:
        return "0-15"
    if age >= 82:
        return "82+"
    return str(age)

def nearest_deductible(d) -> str:
    opts = [0, 425, 850, 1700, 3400, 8500]
    # Accept int or string
    try:
        d_int = int(d)
    except (ValueError, TypeError):
        return "0"
    nearest = min(opts, key=lambda x: abs(x - d_int))
    return str(nearest)


# ── Setup ─────────────────────────────────────────────────────

@app.post("/setup")
def setup(x_setup_key: str = Header(...)):
    require_setup_key(x_setup_key)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bupa_ww_rates (
            id          SERIAL PRIMARY KEY,
            zone        VARCHAR(20)    NOT NULL,
            deductible  VARCHAR(10)    NOT NULL,
            age_label   VARCHAR(10)    NOT NULL,
            monthly     NUMERIC(10,2)  NOT NULL,
            annual      NUMERIC(10,2)  NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bupa_ww_zones (
            country     VARCHAR(100)   PRIMARY KEY,
            zone        VARCHAR(20)    NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bupa_ww_rate_history (
            id            SERIAL PRIMARY KEY,
            change_type   VARCHAR(20)    NOT NULL,
            instruction   TEXT,
            filters       JSONB,
            adjustment    JSONB,
            rows_affected INTEGER,
            updated_at    TIMESTAMPTZ    DEFAULT NOW(),
            snapshot      JSONB
        );
        CREATE INDEX IF NOT EXISTS idx_bupa_ww_lookup
            ON bupa_ww_rates(zone, deductible, age_label);
    """)
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "ok", "message": "Tables created"}


# ── Ingest ────────────────────────────────────────────────────

@app.post("/ingest")
def ingest(x_setup_key: str = Header(...)):
    require_setup_key(x_setup_key)
    conn = get_conn()
    cur = conn.cursor()

    # Ingest rates
    cur.execute("TRUNCATE bupa_ww_rates RESTART IDENTITY")
    rate_rows = []
    for zone, deductibles in RATES.items():
        for ded_str, ages in deductibles.items():
            for age_label, (monthly, annual) in ages.items():
                rate_rows.append((zone, ded_str, age_label, monthly, annual))
    execute_values(cur,
        "INSERT INTO bupa_ww_rates (zone, deductible, age_label, monthly, annual) VALUES %s",
        rate_rows)

    # Ingest country→zone map
    cur.execute("TRUNCATE bupa_ww_zones")
    zone_rows = list(COUNTRY_ZONE_MAP.items())
    execute_values(cur,
        "INSERT INTO bupa_ww_zones (country, zone) VALUES %s",
        zone_rows)

    conn.commit()
    cur.close()
    conn.close()
    return {
        "status": "ok",
        "rates_ingested": len(rate_rows),
        "countries_ingested": len(zone_rows)
    }


# ── Health ────────────────────────────────────────────────────

@app.get("/health")
def health():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM bupa_ww_rates")
    rate_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM bupa_ww_zones")
    zone_count = cur.fetchone()[0]
    cur.close()
    conn.close()
    return {
        "status": "ok",
        "product": PRODUCT,
        "insurer": INSURER,
        "administrator": ADMINISTRATOR,
        "currency": CURRENCY,
        "effective_date": EFFECTIVE_DATE,
        "rate_rows": rate_count,
        "zone_rows": zone_count,
        "deductibles": DEDUCTIBLES,
    }


# ── Zones / Countries ─────────────────────────────────────────

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
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT country FROM bupa_ww_zones ORDER BY country")
    countries = [r[0] for r in cur.fetchall()]
    cur.close()
    conn.close()
    return {"countries": countries}


@app.get("/country/{country}/zone")
def country_zone(country: str, x_api_key: str = Header(...)):
    require_api_key(x_api_key)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT zone FROM bupa_ww_zones WHERE country = %s", (country,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail=f"Country not found: {country}")
    base_zone = row[0]
    us_zone = base_zone + "_us"
    return {
        "country": country,
        "zone": base_zone,
        "zone_with_us": us_zone if us_zone in RATES else base_zone
    }


@app.get("/deductibles")
def list_deductibles(x_api_key: str = Header(...)):
    require_api_key(x_api_key)
    return {"deductibles_usd": DEDUCTIBLES}


# ── Quote models ──────────────────────────────────────────────

class QuoteRequest(BaseModel):
    country: str
    age: int
    deductible: str = "0"
    include_us: bool = False
    payment_frequency: str = "annual"

class QuoteByZoneRequest(BaseModel):
    zone: str
    age: int
    deductible: str = "0"
    payment_frequency: str = "annual"


# ── Quote helpers ─────────────────────────────────────────────

def db_get_rate(cur, zone: str, deductible: str, age_label: str) -> dict:
    cur.execute("""
        SELECT monthly, annual FROM bupa_ww_rates
        WHERE zone = %s AND deductible = %s AND age_label = %s
    """, (zone, deductible, age_label))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404,
            detail=f"No rate found for zone={zone}, deductible={deductible}, age={age_label}")
    return {"monthly": float(row[0]), "annual": float(row[1])}

def resolve_zone_db(cur, country: str, include_us: bool) -> str:
    cur.execute("SELECT zone FROM bupa_ww_zones WHERE country = %s", (country,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Country not found: {country}")
    base_zone = row[0]
    if include_us:
        us_zone = base_zone + "_us"
        cur.execute("SELECT 1 FROM bupa_ww_rates WHERE zone = %s LIMIT 1", (us_zone,))
        if cur.fetchone():
            return us_zone
    return base_zone


# ── Quote ─────────────────────────────────────────────────────

@app.post("/quote")
def quote(req: QuoteRequest, x_api_key: str = Header(...)):
    require_api_key(x_api_key)
    ded = nearest_deductible(req.deductible)
    if ded not in DEDUCTIBLES:
        raise HTTPException(status_code=400,
            detail=f"Invalid deductible '{req.deductible}'. Valid: {DEDUCTIBLES}")

    conn = get_conn()
    cur = conn.cursor()
    zone = resolve_zone_db(cur, req.country, req.include_us)
    age_label = normalise_age(req.age)
    rate = db_get_rate(cur, zone, ded, age_label)
    cur.close()
    conn.close()

    premium = rate["monthly"] if req.payment_frequency == "monthly" else rate["annual"]
    return {
        "country": req.country,
        "zone": zone,
        "age": req.age,
        "age_band": age_label,
        "deductible_usd": ded,
        "include_us": req.include_us,
        "currency": CURRENCY,
        "payment_frequency": req.payment_frequency,
        "premium": premium,
        "monthly": rate["monthly"],
        "annual": rate["annual"],
        "annual_premium": rate["annual"],
        "effective_date": EFFECTIVE_DATE,
        "insurer": INSURER,
        "product": PRODUCT,
    }


@app.post("/quote/zone")
def quote_by_zone(req: QuoteByZoneRequest, x_api_key: str = Header(...)):
    require_api_key(x_api_key)
    ded = nearest_deductible(req.deductible)
    if ded not in DEDUCTIBLES:
        raise HTTPException(status_code=400,
            detail=f"Invalid deductible '{req.deductible}'. Valid: {DEDUCTIBLES}")

    conn = get_conn()
    cur = conn.cursor()
    age_label = normalise_age(req.age)
    rate = db_get_rate(cur, req.zone, ded, age_label)
    cur.close()
    conn.close()

    premium = rate["monthly"] if req.payment_frequency == "monthly" else rate["annual"]
    return {
        "zone": req.zone,
        "age": req.age,
        "age_band": age_label,
        "deductible_usd": ded,
        "currency": CURRENCY,
        "payment_frequency": req.payment_frequency,
        "premium": premium,
        "monthly": rate["monthly"],
        "annual": rate["annual"],
        "annual_premium": rate["annual"],
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
    require_api_key(x_api_key)
    conn = get_conn()
    cur = conn.cursor()
    zone = resolve_zone_db(cur, country, include_us)
    age_label = normalise_age(age)

    cur.execute("""
        SELECT deductible, monthly, annual FROM bupa_ww_rates
        WHERE zone = %s AND age_label = %s
        ORDER BY deductible::integer ASC
    """, (zone, age_label))
    results = cur.fetchall()
    cur.close()
    conn.close()

    return {
        "country": country,
        "zone": zone,
        "age": age,
        "age_band": age_label,
        "include_us": include_us,
        "currency": CURRENCY,
        "effective_date": EFFECTIVE_DATE,
        "insurer": INSURER,
        "product": PRODUCT,
        "rates": [
            {"deductible_usd": r[0], "monthly": float(r[1]), "annual": float(r[2])}
            for r in results
        ],
    }


# ── Admin: adjust rates ───────────────────────────────────────

class AdjustmentRule(BaseModel):
    filters: dict = {}
    adjustment: dict = {}

class AdjustRequest(BaseModel):
    filters: dict = {}
    adjustment: dict = {}
    rules: Optional[List[AdjustmentRule]] = None
    confirmed: bool = False
    instruction: Optional[str] = None


def build_where(filters: dict):
    where = ["1=1"]
    params = []
    if filters.get("zones"):
        where.append("zone = ANY(%s)")
        params.append(filters["zones"])
    if filters.get("deductibles"):
        where.append("deductible = ANY(%s)")
        params.append([str(d) for d in filters["deductibles"]])
    if filters.get("age_labels"):
        where.append("age_label = ANY(%s)")
        params.append(filters["age_labels"])
    return " AND ".join(where), params


def apply_adjustment(cur, where_clause: str, params: list, adj: dict) -> int:
    adj_type  = adj.get("type", "percentage")
    adj_value = float(adj.get("value", 0))

    if adj_type == "percentage":
        cur.execute(f"""
            UPDATE bupa_ww_rates
            SET monthly = ROUND(monthly * (1 + %s / 100.0), 2),
                annual  = ROUND(annual  * (1 + %s / 100.0), 2)
            WHERE {where_clause}
        """, [adj_value, adj_value] + params)
    elif adj_type == "fixed_amount":
        cur.execute(f"""
            UPDATE bupa_ww_rates
            SET monthly = ROUND(monthly + %s, 2),
                annual  = ROUND(annual  + %s, 2)
            WHERE {where_clause}
        """, [adj_value, adj_value] + params)
    elif adj_type == "set_value":
        cur.execute(f"""
            UPDATE bupa_ww_rates
            SET annual  = %s,
                monthly = ROUND(%s / 12.0, 2)
            WHERE {where_clause}
        """, [adj_value, adj_value] + params)

    return cur.rowcount


@app.post("/admin/rates/adjust")
def admin_adjust(req: AdjustRequest, x_admin_key: str = Header(...)):
    require_admin_key(x_admin_key)
    conn = get_conn()
    cur = conn.cursor()

    # Support both single rule and multi-rule
    rules = req.rules if req.rules else [
        AdjustmentRule(filters=req.filters, adjustment=req.adjustment)
    ]

    if not req.confirmed:
        # Preview mode
        total_rows = 0
        all_samples = []
        for rule in rules:
            where_clause, params = build_where(rule.filters)
            cur.execute(f"SELECT COUNT(*) FROM bupa_ww_rates WHERE {where_clause}", params)
            count = cur.fetchone()[0]
            total_rows += count

            cur.execute(f"""
                SELECT zone, deductible, age_label, monthly, annual
                FROM bupa_ww_rates WHERE {where_clause} LIMIT 2
            """, params)
            for row in cur.fetchall():
                adj_type  = rule.adjustment.get("type", "percentage")
                adj_value = float(rule.adjustment.get("value", 0))
                before = float(row[4])
                if adj_type == "percentage":
                    after = round(before * (1 + adj_value / 100), 2)
                elif adj_type == "fixed_amount":
                    after = round(before + adj_value, 2)
                else:
                    after = adj_value
                all_samples.append({
                    "zone": row[0], "deductible": row[1],
                    "age_label": row[2], "before": before, "after": after
                })

        cur.close()
        conn.close()
        return {
            "status": "preview",
            "rows_affected": total_rows,
            "sample_changes": all_samples,
            "confirm_to_apply": True
        }

    # Apply mode — snapshot first
    cur.execute("SELECT id, zone, deductible, age_label, monthly, annual FROM bupa_ww_rates")
    snapshot = [
        {"id": r[0], "zone": r[1], "deductible": r[2],
         "age_label": r[3], "monthly": float(r[4]), "annual": float(r[5])}
        for r in cur.fetchall()
    ]

    total_updated = 0
    for rule in rules:
        where_clause, params = build_where(rule.filters)
        total_updated += apply_adjustment(cur, where_clause, params, rule.adjustment)

    # Record history
    cur.execute("""
        INSERT INTO bupa_ww_rate_history
            (change_type, instruction, filters, adjustment, rows_affected, snapshot)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (
        "adjustment",
        req.instruction,
        json.dumps([r.filters for r in rules]),
        json.dumps([r.adjustment for r in rules]),
        total_updated,
        json.dumps(snapshot)
    ))
    history_id = cur.fetchone()[0]

    conn.commit()
    cur.close()
    conn.close()

    return {
        "status": "applied",
        "rows_updated": total_updated,
        "history_id": history_id
    }


# ── Admin: history ────────────────────────────────────────────

@app.get("/admin/rates/history")
def admin_history(x_admin_key: str = Header(...)):
    require_admin_key(x_admin_key)
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT id, change_type, instruction, filters, adjustment,
               rows_affected, updated_at
        FROM bupa_ww_rate_history
        ORDER BY updated_at DESC
        LIMIT 50
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return {"history": [dict(r) for r in rows]}


# ── Admin: rollback ───────────────────────────────────────────

class RollbackRequest(BaseModel):
    history_id: int

@app.post("/admin/rates/rollback")
def admin_rollback(req: RollbackRequest, x_admin_key: str = Header(...)):
    require_admin_key(x_admin_key)
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT snapshot, rows_affected FROM bupa_ww_rate_history WHERE id = %s",
                (req.history_id,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail=f"History record {req.history_id} not found")

    snapshot = row[0]  # already parsed as list by psycopg2 JSONB

    # Restore snapshot
    for record in snapshot:
        cur.execute("""
            UPDATE bupa_ww_rates
            SET monthly = %s, annual = %s
            WHERE id = %s
        """, (record["monthly"], record["annual"], record["id"]))

    rows_restored = len(snapshot)

    # Record the rollback in history
    cur.execute("""
        INSERT INTO bupa_ww_rate_history
            (change_type, instruction, rows_affected)
        VALUES ('rollback', %s, %s)
    """, (f"Rollback to history_id={req.history_id}", rows_restored))

    conn.commit()
    cur.close()
    conn.close()

    return {
        "status": "rolled_back",
        "history_id": req.history_id,
        "rows_restored": rows_restored
    }


# ── Admin: reimport from rates_data.py ───────────────────────

@app.post("/admin/rates/reimport")
def admin_reimport(x_admin_key: str = Header(...)):
    """Reload all rates from rates_data.py — full replacement."""
    require_admin_key(x_admin_key)
    conn = get_conn()
    cur = conn.cursor()

    # Snapshot before reimport
    cur.execute("SELECT id, zone, deductible, age_label, monthly, annual FROM bupa_ww_rates")
    snapshot = [
        {"id": r[0], "zone": r[1], "deductible": r[2],
         "age_label": r[3], "monthly": float(r[4]), "annual": float(r[5])}
        for r in cur.fetchall()
    ]

    cur.execute("TRUNCATE bupa_ww_rates RESTART IDENTITY")
    rate_rows = []
    for zone, deductibles in RATES.items():
        for ded_str, ages in deductibles.items():
            for age_label, (monthly, annual) in ages.items():
                rate_rows.append((zone, ded_str, age_label, monthly, annual))
    execute_values(cur,
        "INSERT INTO bupa_ww_rates (zone, deductible, age_label, monthly, annual) VALUES %s",
        rate_rows)

    cur.execute("""
        INSERT INTO bupa_ww_rate_history
            (change_type, instruction, rows_affected, snapshot)
        VALUES ('bulk_import', 'Full reimport from rates_data.py', %s, %s)
    """, (len(rate_rows), json.dumps(snapshot)))

    conn.commit()
    cur.close()
    conn.close()

    return {
        "status": "ok",
        "rates_ingested": len(rate_rows)
    }


# ── Run ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
