import json
import unittest
from pathlib import Path

import httpx

from app.client import PortalAuthenticationError
from app.main import app


class FakePortalClient:
    async def get_meters(self) -> object:
        return [{"meter_id": "J100000", "serial_number": "SE33962"}]

    async def get_meter(self, meter_id: str) -> object:
        return {"meter_id": meter_id, "serial_number": "SE33962"}

    async def get_consumption(self, meter_id: str) -> object:
        return {"meter_id": meter_id, "readings": []}

    async def get_hierarchy(self, meter_id: str) -> object:
        return {
            "meter_id": meter_id,
            "path": [
                {"level": "zone", "name": "Jaipur Zone 1", "code": "Z-01"}
            ],
        }


class FailingPortalClient(FakePortalClient):
    async def get_meters(self) -> object:
        raise PortalAuthenticationError("credentials rejected")


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.original_client = getattr(app.state, "portal_client", None)
        app.state.portal_client = FakePortalClient()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        )

    async def asyncTearDown(self) -> None:
        await self.client.aclose()
        if self.original_client is None:
            del app.state.portal_client
        else:
            app.state.portal_client = self.original_client

    async def test_read_routes_return_portal_json(self) -> None:
        expected = {
            "/api/v1/meters": [{"meter_id": "J100000", "serial_number": "SE33962"}],
            "/api/v1/meters/J100000": {"meter_id": "J100000", "serial_number": "SE33962"},
            "/api/v1/meters/J100000/consumption": {"meter_id": "J100000", "readings": []},
            "/api/v1/hierarchy/J100000": {
                "meter_id": "J100000",
                "path": [
                    {"level": "zone", "name": "Jaipur Zone 1", "code": "Z-01"}
                ],
            },
        }

        for path, body in expected.items():
            with self.subTest(path=path):
                response = await self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), body)

    async def test_upstream_authentication_failure_is_a_502(self) -> None:
        app.state.portal_client = FailingPortalClient()
        response = await self.client.get("/api/v1/meters")
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], "credentials rejected")

    async def test_openapi_snapshot_matches_application(self) -> None:
        snapshot_path = Path(__file__).resolve().parents[1] / "openapi.json"
        self.assertEqual(json.loads(snapshot_path.read_text()), app.openapi())


if __name__ == "__main__":
    unittest.main()
