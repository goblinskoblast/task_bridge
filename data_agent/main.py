from __future__ import annotations

import logging

from fastapi import Depends, FastAPI, HTTPException, Request

from config import INTERNAL_API_TOKEN
from db.database import init_db
from .monitor_scheduler import start_data_agent_monitor_scheduler, stop_data_agent_monitor_scheduler
from .point_stats_scheduler import start_point_statistics_scheduler, stop_point_statistics_scheduler
from .models import (
    DataAgentChatRequest,
    DataAgentChatResponse,
    DataAgentDebugResponse,
    MonitorDeleteResponse,
    MonitorsListResponse,
    SystemConnectRequest,
    SystemConnectResponse,
    SystemsListResponse,
)
from .service import service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


app = FastAPI(title="TaskBridge DataAgent", version="0.1.0")


def verify_internal_api_access(request: Request) -> None:
    if not INTERNAL_API_TOKEN:
        return

    provided_token = request.headers.get("X-Internal-Token", "").strip()
    if not provided_token or provided_token != INTERNAL_API_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")


@app.on_event("startup")
async def startup() -> None:
    init_db()
    start_data_agent_monitor_scheduler()
    start_point_statistics_scheduler()


@app.on_event("shutdown")
async def shutdown() -> None:
    stop_data_agent_monitor_scheduler()
    stop_point_statistics_scheduler()


@app.get("/health")
async def health() -> dict:
    return service.health()


@app.post("/chat", response_model=DataAgentChatResponse)
async def chat(payload: DataAgentChatRequest, _: None = Depends(verify_internal_api_access)) -> DataAgentChatResponse:
    return await service.chat(payload)


@app.post("/systems/connect", response_model=SystemConnectResponse)
async def connect_system(payload: SystemConnectRequest, _: None = Depends(verify_internal_api_access)) -> SystemConnectResponse:
    return await service.connect_system(payload)


@app.get("/systems/{user_id}", response_model=SystemsListResponse)
async def list_systems(user_id: int, _: None = Depends(verify_internal_api_access)) -> SystemsListResponse:
    return SystemsListResponse(systems=service.list_systems(user_id))


@app.get("/monitors/{user_id}", response_model=MonitorsListResponse)
async def list_monitors(user_id: int, _: None = Depends(verify_internal_api_access)) -> MonitorsListResponse:
    return MonitorsListResponse(monitors=service.list_monitors(user_id))


@app.delete("/monitors/{user_id}/{monitor_id}", response_model=MonitorDeleteResponse)
async def delete_monitor(user_id: int, monitor_id: int, _: None = Depends(verify_internal_api_access)) -> MonitorDeleteResponse:
    return service.delete_monitor(user_id, monitor_id)


@app.get("/debug/{user_id}", response_model=DataAgentDebugResponse)
async def get_debug(user_id: int, _: None = Depends(verify_internal_api_access)) -> DataAgentDebugResponse:
    return service.get_debug_snapshot(user_id)
