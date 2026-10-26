import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    base_url: str = "https://urja-ops.flockenergy.tech"
    username: str = ""
    password: str = ""
    timeout_seconds: float = 10.0
    login_path: str = "/login"
    meter_search_path: str = "/portal/meters/search"
    meter_geo_path_template: str = "/portal/meters/{meter_id}/geo"
    meter_energy_path_template: str = "/portal/meters/{meter_id}/energy"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            base_url=os.getenv("URJA_BASE_URL", cls.base_url).rstrip("/"),
            username=os.getenv("URJA_USERNAME") or os.getenv("URJA_EMAIL", ""),
            password=os.getenv("URJA_PASSWORD", ""),
            timeout_seconds=float(os.getenv("URJA_TIMEOUT_SECONDS", "10")),
            login_path=os.getenv("URJA_LOGIN_PATH", cls.login_path),
            meter_search_path=os.getenv("URJA_METER_SEARCH_PATH", cls.meter_search_path),
            meter_geo_path_template=os.getenv(
                "URJA_METER_GEO_PATH_TEMPLATE",
                cls.meter_geo_path_template,
            ),
            meter_energy_path_template=os.getenv(
                "URJA_METER_ENERGY_PATH_TEMPLATE",
                cls.meter_energy_path_template,
            ),
        )
