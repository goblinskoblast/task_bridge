from __future__ import annotations

import re
from typing import Iterable

from db.models import SavedPoint

from .italian_pizza import resolve_italian_pizza_point
from .monitoring import resolve_user_facing_chat_title

POINT_REPORT_CHAT_FIELDS = {
    "stoplist": ("stoplist_report_chat_id", "stoplist_report_chat_title"),
    "blanks": ("blanks_report_chat_id", "blanks_report_chat_title"),
}


def normalize_delivery_text(value: str | None) -> str:
    normalized = (value or "").lower().replace("ё", "е")
    normalized = re.sub(r"[^a-zа-я0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _city_variants(city: str | None) -> set[str]:
    normalized_city = normalize_delivery_text(city)
    if not normalized_city:
        return set()

    variants = {normalized_city}
    parts = normalized_city.split()
    if len(parts) > 1:
        variants.add(parts[-1])
    return {item for item in variants if item}


def build_point_delivery_aliases(point: SavedPoint) -> set[str]:
    aliases = {
        normalize_delivery_text(point.display_name),
        normalize_delivery_text(point.address),
        normalize_delivery_text(f"{point.city} {point.address}"),
        normalize_delivery_text(point.external_point_key),
    }
    aliases.update(_city_variants(point.city))
    return {alias for alias in aliases if alias}


def build_text_delivery_aliases(text: str | None) -> set[str]:
    aliases = {normalize_delivery_text(text)}
    resolved = resolve_italian_pizza_point(text or "")
    if resolved:
        aliases.update(
            {
                normalize_delivery_text(resolved.display_name),
                normalize_delivery_text(resolved.address),
                normalize_delivery_text(f"{resolved.city} {resolved.address}"),
                normalize_delivery_text(resolved.public_slug),
            }
        )
        aliases.update(_city_variants(resolved.city))
    return {alias for alias in aliases if alias}


def find_delivery_points_for_text(points: Iterable[SavedPoint], text: str | None) -> list[SavedPoint]:
    message_aliases = build_text_delivery_aliases(text)
    if not message_aliases:
        return []

    matched: list[SavedPoint] = []
    for point in points:
        aliases = build_point_delivery_aliases(point)
        if any(
            alias and any(alias in candidate or candidate in alias for candidate in message_aliases if candidate)
            for alias in aliases
        ):
            matched.append(point)
    return matched


def get_point_report_chat(point: SavedPoint | None, category: str | None) -> tuple[int | None, str | None]:
    if point is None:
        return None, None

    fields = POINT_REPORT_CHAT_FIELDS.get((category or "").strip())
    if not fields:
        return None, None

    chat_id = getattr(point, fields[0], None)
    if not chat_id:
        return None, None

    chat_title = resolve_user_facing_chat_title(getattr(point, fields[1], None))
    return int(chat_id), chat_title


def resolve_point_report_chat(
    points: Iterable[SavedPoint],
    *,
    point_name: str | None,
    category: str | None,
) -> tuple[int | None, str | None, SavedPoint | None]:
    normalized_point_name = normalize_delivery_text(point_name)
    if not normalized_point_name:
        return None, None, None

    materialized_points = list(points)
    direct_match = next(
        (item for item in materialized_points if normalize_delivery_text(item.display_name) == normalized_point_name),
        None,
    )
    if direct_match:
        chat_id, chat_title = get_point_report_chat(direct_match, category)
        if chat_id:
            return chat_id, chat_title, direct_match

    matched_points = find_delivery_points_for_text(materialized_points, point_name)
    if len(matched_points) != 1:
        return None, None, direct_match

    chat_id, chat_title = get_point_report_chat(matched_points[0], category)
    if not chat_id:
        return None, None, matched_points[0]
    return chat_id, chat_title, matched_points[0]


def match_saved_point_to_chat_title(points: Iterable[SavedPoint], chat_title: str | None) -> SavedPoint | None:
    normalized_chat_title = normalize_delivery_text(chat_title)
    if not normalized_chat_title:
        return None

    ranked: list[tuple[int, str, SavedPoint]] = []
    for point in points:
        best_score = 0
        for alias in build_point_delivery_aliases(point):
            if not alias:
                continue
            if alias == normalized_chat_title:
                best_score = max(best_score, 100 + len(alias))
            elif alias in normalized_chat_title:
                best_score = max(best_score, 60 + len(alias))
            elif normalized_chat_title in alias:
                best_score = max(best_score, 30 + len(alias))
        if best_score > 0:
            ranked.append((best_score, point.display_name, point))

    if not ranked:
        return None

    ranked.sort(key=lambda item: (-item[0], item[1]))
    top_score = ranked[0][0]
    top_points = [item[2] for item in ranked if item[0] == top_score]
    if len(top_points) != 1:
        return None
    return top_points[0]
