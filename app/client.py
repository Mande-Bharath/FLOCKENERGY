import asyncio
import json
import re
from urllib.parse import quote, urljoin
from typing import Any

import httpx

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - optional in test envs
    BeautifulSoup = None

from app.config import Settings


class PortalError(Exception):
    """Base error for failures communicating with the legacy portal."""


class PortalAuthenticationError(PortalError):
    """The configured credentials were rejected or the session expired."""


class PortalResponseError(PortalError):
    """The portal returned an unexpected or unsuccessful response."""


class UrjaPortalClient:
    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=settings.base_url,
            timeout=settings.timeout_seconds,
            follow_redirects=False,
        )
        self._authenticated = False
        self._login_lock = asyncio.Lock()
        self._browser_page: Any | None = None
        self._browser: Any | None = None
        self._playwright: Any | None = None

    async def aclose(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
            self._browser_page = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
        if self._owns_client:
            await self._client.aclose()

    async def login(self, force: bool = False) -> None:
        async with self._login_lock:
            if self._authenticated and not force:
                return

            email = self.settings.username
            if not email or not self.settings.password:
                raise PortalAuthenticationError(
                    "Set URJA_USERNAME/URJA_EMAIL and URJA_PASSWORD before requesting portal data."
                )

            try:
                response = await self._client.post(
                    self.settings.login_path,
                    data={"email": email, "password": self.settings.password},
                )
            except httpx.RequestError as exc:
                self._authenticated = False
                raise PortalResponseError(
                    "Unable to reach the legacy portal during login."
                ) from exc

            if response.status_code in (401, 403):
                self._authenticated = False
                browser_page = await self._ensure_browser_session()
                if browser_page is None:
                    raise PortalAuthenticationError("The portal rejected the configured credentials.")
                self._authenticated = True
                return

            if response.status_code >= 400 and response.status_code not in (301, 302, 303, 307, 308):
                self._raise_response_error(response)

            self._authenticated = True

    async def get_meters(self) -> list[dict[str, Any]]:
        payload = await self._get_json(
            self.settings.meter_search_path,
            params={"q": "", "page": 1},
        )
        records = self._meter_records(payload)
        if not isinstance(payload, dict):
            return [self._normalize_meter_row(row) for row in records]

        total = self._nonnegative_int(payload.get("total"), len(records))
        page_size = self._nonnegative_int(payload.get("pageSize"), len(records))
        if total and not page_size:
            raise PortalResponseError("The portal returned an invalid meter page size.")

        all_records = list(records)
        page_count = (total + page_size - 1) // page_size if page_size else 1
        for page in range(2, page_count + 1):
            page_payload = await self._get_json(
                self.settings.meter_search_path,
                params={"q": "", "page": page},
            )
            all_records.extend(self._meter_records(page_payload))

        return [self._normalize_meter_row(row) for row in all_records]

    async def get_meter(self, meter_id: str) -> dict[str, Any]:
        safe_id = quote(meter_id, safe="")
        meters = await self.get_meters()
        match = next((row for row in meters if row.get("meter_id") == meter_id), None)

        geo = await self._get_json(self.settings.meter_geo_path_template.format(meter_id=safe_id))
        energy = await self._get_json(self.settings.meter_energy_path_template.format(meter_id=safe_id))

        geo_data = geo.get("data", geo) if isinstance(geo, dict) else {}
        energy_data = energy.get("data", energy) if isinstance(energy, dict) else []

        scraped = await self._scrape_detail_page(meter_id)

        return {
            "meter_id": meter_id,
            "serial_number": scraped.get("serial_number") if scraped else (match.get("serial_number") if match else None),
            "make": scraped.get("make") if scraped else (match.get("make") if match else None),
            "phase_type": scraped.get("phase_type") if scraped else (match.get("phase_type") if match else None),
            "installation_status": scraped.get("installation_status") if scraped else (match.get("install_status") if match else None),
            "installation_type": scraped.get("installation_type") if scraped else None,
            "dt_code": scraped.get("dt_code") if scraped else (match.get("dt_code") if match else None),
            "hierarchy": scraped.get("hierarchy") if scraped else [],
            "location": {
                "latitude": self._maybe_float(geo_data.get("latitude")),
                "longitude": self._maybe_float(geo_data.get("longitude")),
            },
            "consumption": [self._normalize_reading(row) for row in energy_data],
        }

    async def get_consumption(self, meter_id: str) -> dict[str, Any]:
        safe_id = quote(meter_id, safe="")
        payload = await self._get_json(
            self.settings.meter_energy_path_template.format(meter_id=safe_id),
        )
        readings = payload.get("data", payload) if isinstance(payload, dict) else payload
        return {
            "meter_id": meter_id,
            "readings": [self._normalize_reading(row) for row in readings],
        }

    async def get_hierarchy(self, meter_id: str) -> dict[str, Any]:
        detail = await self._scrape_detail_page(meter_id)
        if not detail or not detail["hierarchy"]:
            raise PortalResponseError(
                f"The portal did not provide a hierarchy breadcrumb for meter {meter_id}."
            )
        return {
            "meter_id": meter_id,
            "path": self._normalize_hierarchy_path(detail["hierarchy"]),
        }

    @staticmethod
    def _meter_records(payload: Any) -> list[dict[str, Any]]:
        records = payload.get("data", payload) if isinstance(payload, dict) else payload
        if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
            raise PortalResponseError(
                "The portal meter-search response did not contain a list of meter objects."
            )
        return records

    @staticmethod
    def _nonnegative_int(value: Any, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed >= 0 else default

    @staticmethod
    def _normalize_hierarchy_path(labels: list[str]) -> list[dict[str, str | None]]:
        code_levels = {
            "Z": "zone",
            "C": "circle",
            "D": "division",
            "SD": "subdivision",
            "SS": "substation",
            "F": "feeder",
            "DT": "distribution_transformer",
        }
        levels = tuple(code_levels.values())
        path: list[dict[str, str | None]] = []
        for index, label in enumerate(labels):
            match = re.fullmatch(r"\s*(.*?)\s*\(([^()]*)\)\s*", label)
            code = match.group(2).strip() if match else None
            code_prefix = re.match(r"[A-Z]+", code or "")
            path.append(
                {
                    "level": (
                        code_levels[code_prefix.group(0)]
                        if code_prefix and code_prefix.group(0) in code_levels
                        else levels[index] if index < len(levels) else "unknown"
                    ),
                    "name": match.group(1).strip() if match else label.strip(),
                    "code": code,
                }
            )
        return path

    async def _ensure_browser_session(self) -> Any | None:
        if self._browser_page is not None:
            return self._browser_page
        if BeautifulSoup is None:
            return None

        try:
            from playwright.async_api import async_playwright
        except ImportError:  # pragma: no cover - optional dependency
            return None

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._browser_page = await self._browser.new_page()
        await self._browser_page.goto(f"{self.settings.base_url}/login", wait_until="domcontentloaded")
        await self._browser_page.fill("input[name='email']", self.settings.username)
        await self._browser_page.fill("input[name='password']", self.settings.password)
        await self._browser_page.click("button[type='submit']")
        try:
            await self._browser_page.wait_for_url("**/meters", timeout=15000)
        except Exception:
            return None
        return self._browser_page

    async def _browser_get_json(self, path: str, *, params: dict[str, Any] | None = None) -> Any | None:
        page = await self._ensure_browser_session()
        if page is None:
            return None

        url = f"{self.settings.base_url}{path}"
        query = ""
        if params:
            query = "&".join(f"{key}={value}" for key, value in params.items())
            url = f"{url}?{query}"
        try:
            response = await page.goto(url, wait_until="domcontentloaded")
            raw = await page.content()
            if response is None or response.status >= 400:
                return None
            if raw.strip().startswith("<"):
                return self._extract_json_from_html(raw)
            return json.loads(raw)
        except Exception:
            return None

    @staticmethod
    def _extract_json_from_html(raw: str) -> Any:
        text = raw.strip()
        match = re.search(r"<pre>(.*)</pre>", text, flags=re.DOTALL | re.IGNORECASE)
        if match:
            text = match.group(1)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    async def _scrape_detail_page(self, meter_id: str) -> dict[str, Any] | None:
        if not self.settings.username or not self.settings.password:
            return None
        if BeautifulSoup is None:
            return None

        page = await self._ensure_browser_session()
        if page is None:
            return None

        try:
            await page.goto(f"{self.settings.base_url}/meters/{meter_id}", wait_until="networkidle")
            html = await page.content()
        except Exception:
            return None

        return self._parse_detail_html(html)

    @staticmethod
    def _parse_detail_html(html: str) -> dict[str, Any] | None:
        if BeautifulSoup is None:
            return None

        soup = BeautifulSoup(html, "html.parser")
        pairs: dict[str, str] = {}
        current_label: str | None = None

        for tag in soup.find_all(["dt", "dd", "term", "definition"]):
            label = tag.get_text(" ", strip=True)
            if tag.name in {"dt", "term"}:
                current_label = label
                continue
            if tag.name in {"dd", "definition"} and current_label:
                pairs[current_label] = label
                current_label = None

        hierarchy: list[str] = []
        nav = None
        nav_candidates = soup.select("nav, [role='navigation']")
        for candidate in nav_candidates:
            nav_text = candidate.get_text(" › ", strip=True)
            if "Jaipur Zone 1" in nav_text or "Circle 1" in nav_text or "DT-" in nav_text or "Substation" in nav_text:
                nav = candidate
                break
        if nav is None and nav_candidates:
            nav = nav_candidates[0]

        if nav:
            nav_text = nav.get_text(" › ", strip=True)
            hierarchy = [segment.strip() for segment in re.split(r"\s*›\s*|\s*>\s*", nav_text) if segment.strip()]

        if not pairs and not hierarchy:
            return None

        dt_code = pairs.get("DT Code") or pairs.get("DT")
        if not dt_code and nav:
            match = re.search(r"\((DT-[^)]*)\)", nav.get_text(" ", strip=True))
            if match:
                dt_code = match.group(1)

        return {
            "meter_id": pairs.get("Meter ID"),
            "serial_number": pairs.get("Serial No") or pairs.get("Serial Number"),
            "make": pairs.get("Make"),
            "phase_type": pairs.get("Phase Type"),
            "installation_status": pairs.get("Installation Status"),
            "installation_type": pairs.get("Installation Type"),
            "dt_code": dt_code,
            "hierarchy": hierarchy,
        }

    async def _get_json(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        if not self._authenticated:
            await self.login()

        try:
            response = await self._client.get(path, params=params)
        except httpx.RequestError as exc:
            raise PortalResponseError("Unable to reach the legacy portal.") from exc

        if response.status_code in (401, 403) or self._is_login_redirect(response):
            self._authenticated = False
            await self.login(force=True)
            try:
                response = await self._client.get(path, params=params)
            except httpx.RequestError as exc:
                raise PortalResponseError(
                    "Unable to reach the legacy portal after re-authentication."
                ) from exc

        if response.status_code in (401, 403) or self._is_login_redirect(response):
            self._authenticated = False
            browser_payload = await self._browser_get_json(path, params=params)
            if browser_payload is not None:
                return browser_payload
            raise PortalAuthenticationError("The portal session is no longer authorized.")
        if response.status_code >= 400:
            self._raise_response_error(response)

        return self._decode_json_response(response)

    @staticmethod
    def _decode_json_response(response: httpx.Response) -> Any:
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type.lower():
            try:
                return response.json()
            except ValueError as exc:
                raise PortalResponseError(
                    "The portal returned malformed JSON instead of a usable payload."
                ) from exc

        raw_text = response.text.strip()
        if not raw_text:
            raise PortalResponseError("The portal returned an empty response body.")

        if "<pre>" in raw_text.lower() and "</pre>" in raw_text.lower():
            match = re.search(r"<pre>(.*)</pre>", raw_text, flags=re.DOTALL | re.IGNORECASE)
            if match:
                raw_text = match.group(1).strip()

        try:
            return json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise PortalResponseError(
                "The portal response was not JSON; inspect its actual protocol before parsing HTML."
            ) from exc

    @staticmethod
    def _normalize_meter_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "meter_id": row.get("meterId") or row.get("meter_id"),
            "serial_number": row.get("serialNo") or row.get("serial_number"),
            "make": row.get("make"),
            "phase_type": row.get("phaseType") or row.get("phase_type"),
            "install_status": row.get("installStatus") or row.get("install_status"),
            "dt_code": row.get("dtCode") or row.get("dt_code"),
        }

    @staticmethod
    def _normalize_reading(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "timestamp": row.get("timestamp"),
            "kwh": UrjaPortalClient._maybe_float(row.get("kwh")),
            "kvah": UrjaPortalClient._maybe_float(row.get("kvah")),
            "volt_r": UrjaPortalClient._maybe_float(row.get("voltR") or row.get("volt_r")),
        }

    @staticmethod
    def _maybe_float(value: Any) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _is_login_redirect(response: httpx.Response) -> bool:
        location = response.headers.get("location", "")
        return response.status_code in (301, 302, 303, 307, 308) and (
            "login" in urljoin(str(response.request.url), location).lower()
        )

    @staticmethod
    def _raise_response_error(response: httpx.Response) -> None:
        raise PortalResponseError(
            f"The portal returned HTTP {response.status_code} for {response.request.url.path}."
        )
