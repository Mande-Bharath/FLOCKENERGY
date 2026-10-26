import unittest
from collections.abc import Awaitable, Callable

import httpx

from app.client import (
    PortalAuthenticationError,
    PortalResponseError,
    UrjaPortalClient,
)
from app.config import Settings


class UrjaPortalClientTests(unittest.IsolatedAsyncioTestCase):
    def settings(self) -> Settings:
        return Settings(
            base_url="https://portal.example",
            username="operator@example.com",
            password="secret",
        )

    def client_for(
        self,
        handler: Callable[[httpx.Request], Awaitable[httpx.Response]],
        settings: Settings | None = None,
    ) -> UrjaPortalClient:
        http_client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://portal.example",
        )
        self.addAsyncCleanup(http_client.aclose)
        return UrjaPortalClient(settings or self.settings(), http_client)

    async def test_login_uses_email_field(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/login":
                self.assertEqual(request.content.decode(), "email=operator%40example.com&password=secret")
                return httpx.Response(200, headers={"set-cookie": "session=test"})
            self.assertEqual(request.headers.get("cookie"), "session=test")
            return httpx.Response(200, json={"data": [{"meterId": "J100000"}]})

        client = self.client_for(handler)
        self.assertEqual(await client.get_meters(), [{"meter_id": "J100000", "serial_number": None, "make": None, "phase_type": None, "install_status": None, "dt_code": None}])

    async def test_meter_list_fetches_all_upstream_pages(self) -> None:
        requested_pages: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/login":
                return httpx.Response(200, headers={"set-cookie": "session=test"})
            page = request.url.params["page"]
            requested_pages.append(page)
            if page == "1":
                return httpx.Response(
                    200,
                    json={
                        "data": [{"meterId": "J100000"}],
                        "total": 2,
                        "page": 1,
                        "pageSize": 1,
                    },
                )
            return httpx.Response(
                200,
                json={
                    "data": [{"meterId": "J100001"}],
                    "total": 2,
                    "page": 2,
                    "pageSize": 1,
                },
            )

        client = self.client_for(handler)

        meters = await client.get_meters()

        self.assertEqual(requested_pages, ["1", "2"])
        self.assertEqual([meter["meter_id"] for meter in meters], ["J100000", "J100001"])

    def test_hierarchy_labels_are_normalized_into_levels(self) -> None:
        self.assertEqual(
            UrjaPortalClient._normalize_hierarchy_path(
                ["Jaipur Zone 1 (Z-01)", "Circle 1 (C-01)", "Feeder 1 (F-001)"]
            ),
            [
                {"level": "zone", "name": "Jaipur Zone 1", "code": "Z-01"},
                {"level": "circle", "name": "Circle 1", "code": "C-01"},
                {"level": "feeder", "name": "Feeder 1", "code": "F-001"},
            ],
        )

    async def test_login_redirect_triggers_one_reauthentication(self) -> None:
        login_count = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal login_count
            if request.url.path == "/login":
                login_count += 1
                return httpx.Response(200)
            if login_count == 1:
                return httpx.Response(302, headers={"location": "/login"})
            return httpx.Response(200, json={"data": []})

        client = self.client_for(handler)

        self.assertEqual(await client.get_meters(), [])
        self.assertEqual(login_count, 2)

    async def test_unauthorized_response_triggers_one_reauthentication(self) -> None:
        login_count = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal login_count
            if request.url.path == "/login":
                login_count += 1
                return httpx.Response(200)
            if login_count == 1:
                return httpx.Response(401)
            return httpx.Response(200, json={"data": []})

        client = self.client_for(handler)

        self.assertEqual(await client.get_meters(), [])
        self.assertEqual(login_count, 2)

    async def test_missing_credentials_fail_explicitly(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": []})

        client = self.client_for(
            handler,
            Settings(base_url="https://portal.example"),
        )

        with self.assertRaises(PortalAuthenticationError):
            await client.get_meters()

    async def test_html_pre_json_is_decoded(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/login":
                return httpx.Response(200, headers={"set-cookie": "session=test"})
            return httpx.Response(200, text='<pre>{"data":[{"meterId":"J100000","serialNo":"SE33962"}]}</pre>')

        client = self.client_for(handler)
        self.assertEqual(await client.get_meters(), [{"meter_id": "J100000", "serial_number": "SE33962", "make": None, "phase_type": None, "install_status": None, "dt_code": None}])


if __name__ == "__main__":
    unittest.main()
