from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request

from app.client import (
    PortalAuthenticationError,
    PortalError,
    UrjaPortalClient,
)
from app.config import Settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    client = UrjaPortalClient(Settings.from_env())
    app.state.portal_client = client
    try:
        yield
    finally:
        await client.aclose()


app = FastAPI(
    title="Flock Energy - Urja Meter Ops API",
    version="0.1.0",
    description=(
        "A read-only REST adapter for the verified Urja Meter Ops portal protocol."
    ),
    lifespan=lifespan,
)


def get_portal_client(request: Request) -> UrjaPortalClient:
    return request.app.state.portal_client


async def call_portal(request: Request, method: str, *args: str) -> object:
    client = get_portal_client(request)
    try:
        return await getattr(client, method)(*args)
    except PortalAuthenticationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except PortalError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/api/v1/meters",
    tags=["meters"],
    responses={502: {"description": "The upstream portal could not serve the request."}},
)
async def list_meters(request: Request) -> object:
    return await call_portal(request, "get_meters")


@app.get(
    "/api/v1/meters/{meter_id}",
    tags=["meters"],
    responses={502: {"description": "The upstream portal could not serve the request."}},
)
async def read_meter(meter_id: str, request: Request) -> object:
    return await call_portal(request, "get_meter", meter_id)


@app.get(
    "/api/v1/meters/{meter_id}/consumption",
    tags=["meters"],
    responses={502: {"description": "The upstream portal could not serve the request."}},
)
async def read_consumption(meter_id: str, request: Request) -> object:
    return await call_portal(request, "get_consumption", meter_id)


@app.get(
    "/api/v1/hierarchy/{meter_id}",
    tags=["hierarchy"],
    responses={502: {"description": "The upstream portal could not serve the request."}},
)
async def read_hierarchy(meter_id: str, request: Request) -> object:
    return await call_portal(request, "get_hierarchy", meter_id)
