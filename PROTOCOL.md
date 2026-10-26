# Urja Meter Ops protocol notes

## What I verified live

I checked the production portal in a real authenticated browser session. The important finding is that this is not a conventional JSON API with a `POST /login` that accepts `username` and `password` fields. The app is a SvelteKit portal that uses a standard browser form with a same-origin session cookie.

### Authentication workflow

- Login page: `https://urja-ops.flockenergy.tech/login`
- Form fields: `email` and `password`
- Submit method: `POST /login`
- Successful login occurs only through the same-origin browser flow; a raw `httpx`/`requests` POST from another origin is rejected with `403` and the message `Cross-site POST form submissions are forbidden`.
- After a successful login, the browser keeps a session cookie and navigates to `/meters`.

### Internal data endpoints used by the authenticated app

These are the live internal routes that the app calls after login:

- `GET /portal/meters/search?q=&page=1`
  - Returns a JSON object with a `data` array.
  - Pagination fields: `total` and `pageSize`; observed values were 403 total and 20 per page.
  - Example fields: `meterId`, `serialNo`, `make`, `phaseType`, `installStatus`, `dtCode`.
- `GET /portal/meters/{meter_id}/geo`
  - Returns JSON with `data.latitude` and `data.longitude`.
- `GET /portal/meters/{meter_id}/energy`
  - Returns JSON with a `data` array of consumption readings.
  - Example fields: `timestamp`, `kwh`, `kvah`, `voltR`.

### Meter detail behavior

The browser detail page is served at `/meters/{id}` and includes the meter nameplate and the consumption history. The legacy app does not appear to expose a separate `GET /meters/{id}/consumption` endpoint: the browser loads the detail page and then calls the endpoint above for energy data. This is the key difference between the portal and the original placeholder assumptions.

The detail page also renders the hierarchy breadcrumb from zone to distribution transformer. The apparent internal route `/portal/hierarchy` returned 404 during discovery, so hierarchy is exposed per meter from the detail-page breadcrumb rather than represented as a fabricated global tree.

### Important quirks

- The portal returns JSON payloads wrapped in HTML `<pre>...</pre>` blocks for some requests. The client therefore needs to strip the `<pre>` wrapper before decoding JSON.
- The page is server-rendered HTML but the data used by the browser is mostly fetched from internal JSON endpoints under `/portal`.
- The list endpoint uses 20 records per page and reports `total`, `page`, and `pageSize`. The adapter follows each page to return the complete current dataset.

## Clean API contract we expose

The wrapper service turns these browser-visible and internal routes into a simpler REST API:

- `GET /api/v1/meters`
- `GET /api/v1/meters/{meter_id}`
- `GET /api/v1/meters/{meter_id}/consumption`
- `GET /api/v1/hierarchy/{meter_id}`

The hierarchy endpoint returns that meter's ordered path as normalized level/name/code objects. These endpoints normalize the upstream data into straightforward JSON: meter identifiers, serial numbers, phase type, installation status, geo coordinates, and time-series consumption.
