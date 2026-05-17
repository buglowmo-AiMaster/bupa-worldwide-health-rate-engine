# Raffles-Bupa Worldwide Health Options (WHo) Rate Engine

**Insurer:** Raffles Health Insurance Pte Ltd  
**Administrator:** Bupa Global  
**Product:** Worldwide Health Options (WHo)  
**Currency:** USD  
**Effective:** 1 April 2025

## Overview

FastAPI rate engine serving subscription premiums for the WHo product across 23 zones, 6 deductibles, and all age bands. No database — all rates are baked into `rates_data.py`.

## Zones

| Zone | Key countries |
|------|--------------|
| Zone 1 (with U.S.) | USA, US Minor Outlying Islands |
| Zone 2 | Hong Kong, Israel |
| Zone 3 | Greece |
| Zone 4 | China, Spain, Switzerland, UK, Jersey, Mexico, Honduras, Guatemala, Russia |
| Zone 5 | Most of Americas, W. Europe incl. Germany, Ireland |
| Zone 6 | Thailand, Australia, SE Asia, most of Africa |
| Zone 7 | Japan, Canada, France, Brazil, Philippines |
| Zone 8 | India, Netherlands, Sweden, Norway, Cyprus, Romania, Hungary |
| Zone 9 | Egypt |
| Zone 10 | Singapore |
| Zone 11 | UAE |
| Zone 12 | Indonesia |

Each zone also has a `_us` variant (e.g. `zone6_us`) adding USA coverage.

## Deductibles (USD)

`0` · `425` · `850` · `1700` · `3400` · `8500`

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Service status (no auth) |
| GET | `/zones` | List all zones + deductibles |
| GET | `/countries` | List all supported countries |
| GET | `/country/{country}/zone` | Look up zone for a country |
| POST | `/quote` | Quote by country + age + deductible |
| POST | `/quote/zone` | Quote by zone directly |
| GET | `/quote/all-deductibles` | All deductible options for a country/age |
| GET | `/deductibles` | List valid deductibles |

## Authentication

All endpoints except `/health` require header:
```
x-api-key: who-Mo-2026-secret
```

## Example Request

```bash
curl -X POST https://your-service.railway.app/quote \
  -H "Content-Type: application/json" \
  -H "x-api-key: who-Mo-2026-secret" \
  -d '{
    "country": "Thailand",
    "age": 45,
    "deductible": "0",
    "include_us": false,
    "payment_frequency": "monthly"
  }'
```

## Example Response

```json
{
  "country": "Thailand",
  "zone": "zone6",
  "age": 45,
  "age_band": "45",
  "deductible_usd": "0",
  "include_us": false,
  "currency": "USD",
  "payment_frequency": "monthly",
  "premium": 611.40,
  "monthly": 611.40,
  "annual": 7336.80,
  "effective_date": "2025-04-01",
  "insurer": "Raffles Health Insurance Pte Ltd",
  "product": "Worldwide Health Options (WHo)"
}
```

## Deploy to Railway

1. Push this folder to GitHub
2. New Railway project → Deploy from GitHub repo
3. Set environment variable: `API_KEY=who-Mo-2026-secret`
4. No database needed — zero cold-start overhead

## Local Dev

```bash
pip install -r requirements.txt
API_KEY=who-Mo-2026-secret uvicorn main:app --reload --port 8080
```
