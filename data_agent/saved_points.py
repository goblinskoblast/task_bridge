from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy.orm import Session

from db.models import DataAgentSystem, SavedPoint, User

from .italian_pizza import resolve_italian_pizza_point


DEFAULT_POINT_STATS_INTERVAL_MINUTES = 240
POINT_INTERVAL_PRESETS = [60, 240, 720, 1440]


@dataclass(frozen=True)
class SavedPointSummary:
    id: int
    display_name: str
    provider: str
    is_active: bool
    report_delivery_enabled: bool


class SavedPointError(ValueError):
    pass


class SavedPointService:
    def get_user_by_telegram_id(self, db: Session, telegram_user_id: int) -> User | None:
        return db.query(User).filter(User.telegram_id == telegram_user_id).first()

    def list_points(self, db: Session, telegram_user_id: int, *, active_only: bool = True) -> list[SavedPoint]:
        user = self.get_user_by_telegram_id(db, telegram_user_id)
        if not user:
            return []

        query = db.query(SavedPoint).filter(SavedPoint.user_id == user.id)
        if active_only:
            query = query.filter(SavedPoint.is_active.is_(True))
        return query.order_by(SavedPoint.display_name.asc()).all()

    def get_system_for_user(
        self,
        db: Session,
        telegram_user_id: int,
        *,
        provider: str = "italian_pizza",
    ) -> DataAgentSystem | None:
        user = self.get_user_by_telegram_id(db, telegram_user_id)
        if not user:
            return None

        query = (
            db.query(DataAgentSystem)
            .filter(
                DataAgentSystem.user_id == user.id,
                DataAgentSystem.is_active.is_(True),
            )
            .order_by(DataAgentSystem.last_connected_at.desc().nullslast(), DataAgentSystem.created_at.desc())
        )
        if provider == "italian_pizza":
            query = query.filter(
                (DataAgentSystem.system_name == "italian_pizza")
                | (DataAgentSystem.url.contains("italianpizza"))
            )
        return query.first()

    def get_point(self, db: Session, telegram_user_id: int, point_id: int) -> SavedPoint | None:
        user = self.get_user_by_telegram_id(db, telegram_user_id)
        if not user:
            return None
        return (
            db.query(SavedPoint)
            .filter(SavedPoint.id == point_id, SavedPoint.user_id == user.id)
            .first()
        )

    def save_point(
        self,
        db: Session,
        telegram_user_id: int,
        raw_point: str,
        *,
        provider: str = "italian_pizza",
    ) -> SavedPoint:
        user = self.get_user_by_telegram_id(db, telegram_user_id)
        if not user:
            raise SavedPointError("Пользователь не найден.")

        system = self.get_system_for_user(db, telegram_user_id, provider=provider)
        if not system:
            raise SavedPointError("Сначала подключите систему Italian Pizza, а потом добавляйте точки.")

        normalized = self._normalize_point(raw_point, provider=provider)
        existing = (
            db.query(SavedPoint)
            .filter(
                SavedPoint.user_id == user.id,
                SavedPoint.provider == provider,
                SavedPoint.display_name == normalized["display_name"],
            )
            .first()
        )
        if existing:
            existing.is_active = True
            existing.system_id = system.id
            existing.city = normalized["city"]
            existing.address = normalized["address"]
            existing.external_point_key = normalized["external_point_key"]
            if not existing.stats_interval_minutes or existing.stats_interval_minutes <= 0:
                existing.stats_interval_minutes = DEFAULT_POINT_STATS_INTERVAL_MINUTES
            db.commit()
            db.refresh(existing)
            return existing

        saved_point = SavedPoint(
            user_id=user.id,
            system_id=system.id,
            provider=provider,
            city=normalized["city"],
            address=normalized["address"],
            display_name=normalized["display_name"],
            external_point_key=normalized["external_point_key"],
            is_active=True,
            report_delivery_enabled=False,
            stats_interval_minutes=DEFAULT_POINT_STATS_INTERVAL_MINUTES,
        )
        db.add(saved_point)
        db.commit()
        db.refresh(saved_point)
        return saved_point

    def set_interval(self, db: Session, telegram_user_id: int, point_id: int, interval_minutes: int) -> SavedPoint:
        if interval_minutes <= 0:
            raise SavedPointError("Периодичность должна быть положительной.")
        point = self.get_point(db, telegram_user_id, point_id)
        if not point:
            raise SavedPointError("Точка не найдена.")
        point.stats_interval_minutes = interval_minutes
        db.commit()
        db.refresh(point)
        return point

    def set_report_delivery(self, db: Session, telegram_user_id: int, point_id: int, enabled: bool) -> SavedPoint:
        point = self.get_point(db, telegram_user_id, point_id)
        if not point:
            raise SavedPointError("Точка не найдена.")
        point.report_delivery_enabled = enabled
        db.commit()
        db.refresh(point)
        return point

    def deactivate_point(self, db: Session, telegram_user_id: int, point_id: int) -> SavedPoint:
        point = self.get_point(db, telegram_user_id, point_id)
        if not point:
            raise SavedPointError("Точка не найдена.")
        point.is_active = False
        db.commit()
        db.refresh(point)
        return point

    def summarize(self, points: Iterable[SavedPoint]) -> list[SavedPointSummary]:
        return [
            SavedPointSummary(
                id=item.id,
                display_name=item.display_name,
                provider=item.provider,
                is_active=item.is_active,
                report_delivery_enabled=item.report_delivery_enabled,
            )
            for item in points
        ]

    def _normalize_point(self, raw_point: str, *, provider: str) -> dict[str, str | None]:
        text = (raw_point or "").strip()
        if not text:
            raise SavedPointError("Пришлите город и адрес точки одним сообщением.")

        if provider != "italian_pizza":
            raise SavedPointError("Пока сохранение точек поддерживается только для Italian Pizza.")

        resolved = resolve_italian_pizza_point(text)
        if not resolved:
            raise SavedPointError("Не удалось распознать точку Italian Pizza. Укажите город и адрес точнее.")

        return {
            "city": resolved.city,
            "address": resolved.address,
            "display_name": resolved.display_name,
            "external_point_key": resolved.public_slug,
        }


saved_point_service = SavedPointService()
