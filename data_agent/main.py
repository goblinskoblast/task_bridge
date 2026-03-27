from __future__ import annotations

from fastapi import FastAPI

from .models import DataAgentChatRequest, DataAgentChatResponse, SystemConnectRequest, SystemConnectResponse, SystemsListResponse
from .service import service


app = FastAPI(title="TaskBridge DataAgent", version="0.1.0")


@app.get("/health")
async def health() -> dict:
    return service.health()


@app.post("/chat", response_model=DataAgentChatResponse)
async def chat(payload: DataAgentChatRequest) -> DataAgentChatResponse:
    return service.chat(payload)


@app.post("/systems/connect", response_model=SystemConnectResponse)
async def connect_system(payload: SystemConnectRequest) -> SystemConnectResponse:
    return service.connect_system(payload)


@app.get("/systems/{user_id}", response_model=SystemsListResponse)
async def list_systems(user_id: int) -> SystemsListResponse:
    return SystemsListResponse(systems=service.list_systems(user_id))

