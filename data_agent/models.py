from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

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
    scenario: Optional[str] = None
    status: str = "completed"
    debug_summary: Optional[str] = None


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


class MonitorConfigItem(BaseModel):
    id: int
    monitor_type: str
    point_name: str
    check_interval_minutes: int
    is_active: bool = True
    last_status: Optional[str] = None
    last_checked_at: Optional[datetime] = None
    interval_label: Optional[str] = None
    window_label: Optional[str] = None
    status_label: Optional[str] = None
    last_checked_label: Optional[str] = None
    next_check_label: Optional[str] = None
    last_event_label: Optional[str] = None
    delivery_label: Optional[str] = None
    has_active_alert: bool = False


class MonitorsListResponse(BaseModel):
    monitors: List[MonitorConfigItem] = Field(default_factory=list)


class MonitorDeleteResponse(BaseModel):
    success: bool
    deleted_id: Optional[int] = None
    error: Optional[str] = None


class DataAgentDebugResponse(BaseModel):
    found: bool = False
    trace_id: Optional[str] = None
    scenario: Optional[str] = None
    status: str = "unknown"
    summary: Optional[str] = None
    selected_tools: List[str] = Field(default_factory=list)
    user_message: Optional[str] = None
    answer: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class EmailSummaryItem(BaseModel):
    subject: str
    from_address: str
    date: Optional[datetime] = None
    has_attachments: bool = False


class EmailSummaryResponse(BaseModel):
    accounts_count: int = 0
    messages_count: int = 0
    recent_messages: List[EmailSummaryItem] = Field(default_factory=list)


class CalendarEventItem(BaseModel):
    title: str
    start_at: datetime
    source: str
    task_id: Optional[int] = None


class CalendarEventsResponse(BaseModel):
    events_count: int = 0
    events: List[CalendarEventItem] = Field(default_factory=list)
