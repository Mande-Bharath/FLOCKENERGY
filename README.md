# Flock Energy — Urja Meter Ops API Wrapper

This project exposes a small, documented FastAPI service in front of the legacy Urja Meter Ops portal. The goal is not to replace the portal; it is to give downstream systems a consistent, read-only API that normalizes the portal's messy HTML/JSON mix into clean JSON objects.

## What I built

- A session-aware adapter that logs into the portal using the same browser-compatible flow the app expects.
- A structured JSON layer for meter search results, individual meter detail data, and consumption readings.
- A FastAPI application exposing:
  - `GET /api/v1/meters`
  - `GET /api/v1/meters/{meter_id}`
  - `GET /api/v1/meters/{meter_id}/consumption`
  - `GET /api/v1/hierarchy/{meter_id}`

## Verified portal behavior

After live investigation, the actual workflow is:

1. Open `https://urja-ops.flockenergy.tech/login`
2. Submit a `POST /login` with `email` and `password`
3. Keep the session cookie returned by the browser
4. Query internal JSON endpoints under `/portal` while the session is active

The browser-authenticated portal calls the following internal endpoints:

- `GET /portal/meters/search?q=&page={page}`
- `GET /portal/meters/{meter_id}/geo`
- `GET /portal/meters/{meter_id}/energy`

The meter-search response reports `total` and `pageSize`; the wrapper follows all pages, currently 403 meters at 20 records per page. The portal's `/portal/hierarchy` route returns 404, so the wrapper extracts a meter-specific hierarchy path from the authenticated detail page instead of inventing a global hierarchy.

The app does not expose a separate public `/meters/{id}/consumption` route; the detail page loads the energy data from the internal API.

## Install and run

Requires Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
```

Then set the credentials in `.env`:

```bash
URJA_BASE_URL=https://urja-ops.flockenergy.tech
URJA_USERNAME=replace-with-your-portal-email
URJA_PASSWORD=replace-with-your-portal-password
```

Start the app:

```bash
set -a
. ./.env
set +a
uvicorn app.main:app --reload
```

Open the API docs at:

- http://127.0.0.1:8000/docs
- http://127.0.0.1:8000/openapi.json

## Sample requests

List meters:

```bash
curl -s http://127.0.0.1:8000/api/v1/meters | jq
```

Get a specific meter:

```bash
curl -s http://127.0.0.1:8000/api/v1/meters/J100000 | jq
```

Get consumption:

```bash
curl -s http://127.0.0.1:8000/api/v1/meters/J100000/consumption | jq
```

Get one meter's network path:

```bash
curl -s http://127.0.0.1:8000/api/v1/hierarchy/J100000 | jq
```

## Example response

```json
{
  "meter_id": "J100000",
  "serial_number": "SE33962",
  "make": "HPL",
  "phase_type": "single",
  "installation_status": "Decommissioned",
  "installation_type": "Whole Current",
  "dt_code": "DT-001",
  "hierarchy": [
    "Jaipur Zone 1 (Z-01)",
    "Circle 1 (C-01)",
    "Division 1 (D-01)",
    "Subdivision 1 (SD-01)",
    "Substation 1 (SS-01)",
    "Feeder 1 (F-001)",
    "Malviya Nagar DT 1 (DT-001)"
  ],
  "location": {
    "latitude": 26.938961002479868,
    "longitude": 75.83095696146852
  },
  "consumption": [
    {
      "timestamp": "23/06/2026 23:30",
      "kwh": 48438.74,
      "kvah": 52313.84,
      "volt_r": 226
    }
  ]
}
```

## Assumptions and design choices

- The portal is treated as a read-only source. The wrapper does not write or mutate any upstream state.
- The client uses a real same-origin session because the portal explicitly blocks cross-site form submissions.
- We normalize raw values such as `kwh`, `kvah`, and `voltR` into floats and keep a stable JSON schema rather than leaking raw portal field names.
- The portal has no dedicated global hierarchy API. The wrapper exposes the verified breadcrumb path through `/api/v1/hierarchy/{meter_id}`.

## Intentional omissions

- Playwright is used only where needed for the same-origin login/session and meter breadcrumb; the stable data fields come from the portal's JSON routes.
- No production caching layer or rate-limit backoff is implemented yet.
- The meter list follows all upstream pages, but filtering and caller-controlled page sizing are not exposed yet.

## Reflection

### What assumptions did you make?

I initially assumed the portal would behave like a conventional JSON API, but the live investigation showed that the real app uses a browser form and an authenticated same-origin session. I corrected the design to match the actual login contract and internal `/portal` JSON endpoints instead of guessing at `/login`, `/meters`, and `/meters/{id}/consumption` without verification.

### Which part was the most difficult, and how did you get unstuck?

The hardest part was recognizing that direct cross-site POSTs are rejected and that the portal’s public pages are only the visible shell around internal API calls. I resolved this by authenticating in a real browser and inspecting the actual Network log, which showed the true routes and payloads used by the app.

### If you had another day, what would you improve?

I would add richer validation and error handling around malformed upstream payloads, a small cache layer for meter/search data, and a global hierarchy index built from the portal's breadcrumb metadata with an explicit refresh policy.

### What mistake did you make while solving this?

My first version assumed a conventional endpoint-based login and response model without verifying the live portal. That produced code that looked plausible but was misaligned with the actual system architecture.

### If you were reviewing my own submission, what would I criticise?

I would criticise the lack of deeper data quality validation and the limited hierarchy work; the current wrapper is correct for the observed protocol, but it still treats the portal as a relatively static read-only source rather than a more robust integration platform.

## Protocol and OpenAPI docs

- [PROTOCOL.md](./PROTOCOL.md)
- [openapi.json](./openapi.json)
