import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, Float, ForeignKey, Identity, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, DateTimeUTC, JsonB, Stamped, now, uid

TS = DateTimeUTC(timezone=True)


class User(Stamped, Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uid)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="member")
    rooms: Mapped[list[str]] = mapped_column(JsonB, default=list)
    lang: Mapped[str | None] = mapped_column(String(8))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(TS)


class ApiToken(Stamped, Base):
    __tablename__ = "api_tokens"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scope: Mapped[str] = mapped_column(String(16), default="read")
    rooms: Mapped[list[str]] = mapped_column(JsonB, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(TS)
    last_used_at: Mapped[datetime | None] = mapped_column(TS)


class Home(Stamped, Base):
    __tablename__ = "home"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    name: Mapped[str] = mapped_column(String(120), default="")
    lat: Mapped[float] = mapped_column(Float, default=60.17)
    lon: Mapped[float] = mapped_column(Float, default=24.94)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Helsinki")
    currency: Mapped[str] = mapped_column(String(8), default="EUR")
    price_area: Mapped[str] = mapped_column(String(16), default="FI")
    setup_done: Mapped[bool] = mapped_column(Boolean, default=False)
    settings: Mapped[dict[str, Any]] = mapped_column(JsonB, default=dict)


class Room(Stamped, Base):
    __tablename__ = "rooms"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    floor: Mapped[int] = mapped_column(Integer, default=1)
    outdoor: Mapped[bool] = mapped_column(Boolean, default=False)
    geom: Mapped[dict[str, Any]] = mapped_column(JsonB, default=dict)
    sort: Mapped[int] = mapped_column(Integer, default=0)


class Device(Stamped, Base):
    __tablename__ = "devices"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    room_id: Mapped[str | None] = mapped_column(ForeignKey("rooms.id", ondelete="SET NULL"), index=True)
    source: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(24), default="other")
    model: Mapped[str] = mapped_column(String(160), default="")
    vendor: Mapped[str] = mapped_column(String(80), default="")
    address: Mapped[str] = mapped_column(String(255), default="")
    ieee: Mapped[str | None] = mapped_column(String(32), unique=True)
    ext_id: Mapped[str | None] = mapped_column(String(128), index=True)
    caps: Mapped[list[dict[str, Any]]] = mapped_column(JsonB, default=list)
    state: Mapped[dict[str, Any]] = mapped_column(JsonB, default=dict)
    attrs: Mapped[dict[str, Any]] = mapped_column(JsonB, default=dict)
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen: Mapped[datetime | None] = mapped_column(TS)


class Command(Base):
    __tablename__ = "commands"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uid)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    values: Mapped[dict[str, Any]] = mapped_column(JsonB)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    actor: Mapped[str] = mapped_column(String(160), default="system")
    group_id: Mapped[str | None] = mapped_column(String(64), index=True)
    cause_id: Mapped[int | None] = mapped_column(BigInteger)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, default=now)
    done_at: Mapped[datetime | None] = mapped_column(TS)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (Index("ix_events_ts", "ts"), Index("ix_events_device_ts", "device_id", "ts"))
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    ts: Mapped[datetime] = mapped_column(TS, default=now)
    type: Mapped[str] = mapped_column(String(64), index=True)
    level: Mapped[str] = mapped_column(String(8), default="info")
    params: Mapped[dict[str, Any]] = mapped_column(JsonB, default=dict)
    actor: Mapped[str] = mapped_column(String(160), default="system")
    device_id: Mapped[str | None] = mapped_column(String(128))
    flow_id: Mapped[str | None] = mapped_column(String(64), index=True)
    room_id: Mapped[str | None] = mapped_column(String(64))
    cause_id: Mapped[int | None] = mapped_column(ForeignKey("events.id", ondelete="SET NULL"))


class History(Base):
    __tablename__ = "history"
    __table_args__ = (Index("ix_history_dev_cap_ts", "device_id", "cap", "ts"),)
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    cap: Mapped[str] = mapped_column(String(32))
    ts: Mapped[datetime] = mapped_column(TS, default=now)
    num: Mapped[float | None] = mapped_column(Float)
    txt: Mapped[str | None] = mapped_column(String(255))


class Stat(Base):
    __tablename__ = "stats"
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True)
    cap: Mapped[str] = mapped_column(String(32), primary_key=True)
    hour: Mapped[datetime] = mapped_column(TS, primary_key=True)
    mean: Mapped[float] = mapped_column(Float)
    min: Mapped[float] = mapped_column(Float)
    max: Mapped[float] = mapped_column(Float)
    last: Mapped[float] = mapped_column(Float)
    n: Mapped[int] = mapped_column(Integer)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    key: Mapped[str] = mapped_column(String(160), unique=True)
    level: Mapped[str] = mapped_column(String(8))
    type: Mapped[str] = mapped_column(String(64))
    params: Mapped[dict[str, Any]] = mapped_column(JsonB, default=dict)
    route: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(TS, default=now)
    dismissed_at: Mapped[datetime | None] = mapped_column(TS)


class Scene(Stamped, Base):
    __tablename__ = "scenes"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    icon: Mapped[str] = mapped_column(String(32), default="layers")
    actions: Mapped[dict[str, Any]] = mapped_column(JsonB, default=dict)
    sort: Mapped[int] = mapped_column(Integer, default=0)


class Flow(Stamped, Base):
    __tablename__ = "flows"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    mode: Mapped[str] = mapped_column(String(16), default="single")
    graph: Mapped[dict[str, Any]] = mapped_column(JsonB, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    last_run_at: Mapped[datetime | None] = mapped_column(TS)
    last_result: Mapped[str | None] = mapped_column(String(16))
    runs: Mapped[int] = mapped_column(Integer, default=0)


class FlowVersion(Base):
    __tablename__ = "flow_versions"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    flow_id: Mapped[str] = mapped_column(ForeignKey("flows.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    graph: Mapped[dict[str, Any]] = mapped_column(JsonB)
    author: Mapped[str] = mapped_column(String(160), default="system")
    created_at: Mapped[datetime] = mapped_column(TS, default=now)


class FlowRun(Base):
    __tablename__ = "flow_runs"
    __table_args__ = (Index("ix_flow_runs_flow_started", "flow_id", "started_at"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uid)
    flow_id: Mapped[str] = mapped_column(ForeignKey("flows.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(16), default="run")
    dry: Mapped[bool] = mapped_column(Boolean, default=False)
    cause_id: Mapped[int | None] = mapped_column(BigInteger)
    trace: Mapped[list[Any]] = mapped_column(JsonB, default=list)
    ctx: Mapped[dict[str, Any]] = mapped_column(JsonB, default=dict)
    started_at: Mapped[datetime] = mapped_column(TS, default=now)
    finished_at: Mapped[datetime | None] = mapped_column(TS)


class Extension(Stamped, Base):
    __tablename__ = "extensions"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    version: Mapped[str] = mapped_column(String(32))
    trust: Mapped[str] = mapped_column(String(16), default="community")
    status: Mapped[str] = mapped_column(String(16), default="installing")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    manifest: Mapped[dict[str, Any]] = mapped_column(JsonB, default=dict)
    settings: Mapped[dict[str, Any]] = mapped_column(JsonB, default=dict)
    grants: Mapped[list[str]] = mapped_column(JsonB, default=list)
    error: Mapped[str | None] = mapped_column(Text)
    restarts: Mapped[int] = mapped_column(Integer, default=0)
    pid: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(TS)


class Dashboard(Stamped, Base):
    __tablename__ = "dashboards"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    widgets: Mapped[list[dict[str, Any]]] = mapped_column(JsonB, default=list)
    sort: Mapped[int] = mapped_column(Integer, default=0)


class Backup(Base):
    __tablename__ = "backups"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(16), default="manual")
    status: Mapped[str] = mapped_column(String(16), default="running")
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    path: Mapped[str] = mapped_column(String(255), default="")
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, default=now)
    finished_at: Mapped[datetime | None] = mapped_column(TS)


class AiSettings(Stamped, Base):
    __tablename__ = "ai_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    base_url: Mapped[str] = mapped_column(String(255), default="https://openrouter.ai/api/v1")
    model: Mapped[str] = mapped_column(String(160), default="deepseek/deepseek-v4.1-flash")
    api_key: Mapped[str] = mapped_column(Text, default="")
    temperature: Mapped[float] = mapped_column(Float, default=0.3)
    max_steps: Mapped[int] = mapped_column(Integer, default=12)
    daily_limit: Mapped[int] = mapped_column(Integer, default=0)


class Chat(Stamped, Base):
    __tablename__ = "chats"
    __table_args__ = (Index("ix_chats_user_updated", "user_id", "updated_at"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(160), default="")
    status: Mapped[str] = mapped_column(String(16), default="idle")
    tokens: Mapped[int] = mapped_column(BigInteger, default=0)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (Index("ix_chat_messages_chat", "chat_id", "id"),)
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    chat_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict[str, Any]] = mapped_column(JsonB, default=dict)
    created_at: Mapped[datetime] = mapped_column(TS, default=now)


class ChatAction(Base):
    __tablename__ = "chat_actions"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uid)
    chat_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), index=True)
    tool: Mapped[str] = mapped_column(String(64))
    args: Mapped[dict[str, Any]] = mapped_column(JsonB, default=dict)
    summary: Mapped[str] = mapped_column(String(400), default="")
    status: Mapped[str] = mapped_column(String(16), default="pending")
    result: Mapped[dict[str, Any]] = mapped_column(JsonB, default=dict)
    undo: Mapped[dict[str, Any]] = mapped_column(JsonB, default=dict)
    created_at: Mapped[datetime] = mapped_column(TS, default=now)
    done_at: Mapped[datetime | None] = mapped_column(TS)


class Camera(Stamped, Base):
    __tablename__ = "cameras"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), unique=True)
    driver: Mapped[str] = mapped_column(String(128), index=True)
    config: Mapped[dict[str, Any]] = mapped_column(JsonB, default=dict)
    streams: Mapped[dict[str, Any]] = mapped_column(JsonB, default=dict)
    info: Mapped[dict[str, Any]] = mapped_column(JsonB, default=dict)
    record: Mapped[dict[str, Any]] = mapped_column(JsonB, default=dict)
    health: Mapped[dict[str, Any]] = mapped_column(JsonB, default=dict, server_default=text("'{}'::jsonb"))
    presets: Mapped[list[dict[str, Any]]] = mapped_column(JsonB, default=list, server_default=text("'[]'::jsonb"))
    sort: Mapped[int] = mapped_column(Integer, default=0)


class Media(Base):
    __tablename__ = "media"
    __table_args__ = (Index("ix_media_camera_ts", "camera_id", "created_at"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uid)
    camera_id: Mapped[str | None] = mapped_column(ForeignKey("cameras.id", ondelete="SET NULL"))
    event_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    kind: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(String(512))
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    duration: Mapped[float | None] = mapped_column(Float)
    origin: Mapped[str] = mapped_column(String(160), default="event")
    meta: Mapped[dict[str, Any]] = mapped_column(JsonB, default=dict)
    keep: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(TS, default=now, index=True)


class CameraEvent(Base):
    __tablename__ = "camera_events"
    __table_args__ = (Index("ix_camera_events_camera_ts", "camera_id", "started_at"),)
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(32), default="motion")
    source: Mapped[str] = mapped_column(String(160), default="driver")
    score: Mapped[float | None] = mapped_column(Float)
    data: Mapped[dict[str, Any]] = mapped_column(JsonB, default=dict)
    started_at: Mapped[datetime] = mapped_column(TS, default=now)
    ended_at: Mapped[datetime | None] = mapped_column(TS)
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("media.id", ondelete="SET NULL"))
    clip_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("media.id", ondelete="SET NULL"))
