from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, HttpUrl


class DataAgentChatRequest(BaseModel):
    user_id: int
    message: str = Field(min_length=1, max_length=4000)
    username: Optional[str] = None
    first_name: Optional[str] = None


class DataAgentChatResponse(BaseModel):
    ok: bool = True
    answer: str
    selected_tools: List[str] = Field(default_factory=list)
    trace_id: str


class SystemConnectRequest(BaseModel):
    user_id: int
    url: HttpUrl
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=2048)


class ConnectedSystem(BaseModel):
    system_id: str
    user_id: int
    system_name: str
    url: str
    login: str
    is_active: bool = True
    created_at: datetime


class SystemConnectResponse(BaseModel):
    success: bool
    system: Optional[ConnectedSystem] = None
    error: Optional[str] = None


class SystemsListResponse(BaseModel):
    systems: List[ConnectedSystem] = Field(default_factory=list)

