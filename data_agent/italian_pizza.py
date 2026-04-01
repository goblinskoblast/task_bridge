from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


ITALIAN_PIZZA_PORTAL_URL = "https://tochka.italianpizza.ru/login"


@dataclass(frozen=True)
class ItalianPizzaPoint:
    city: str
    address: str

    @property
    def display_name(self) -> str:
        return f"{self.city}, {self.address}"


ITALIAN_PIZZA_POINTS = [
    ItalianPizzaPoint("Полевской", "Ленина 11"),
    ItalianPizzaPoint("Асбест", "ТЦ Небо, Ленинградская 26"),
    ItalianPizzaPoint("Сухой Лог", "Белинского 40"),
    ItalianPizzaPoint("Реж", "Ленина 17"),
    ItalianPizzaPoint("Верхний Уфалей", "Ленина 147"),
    ItalianPizzaPoint("Артёмовский", "Гагарина 2а"),
    ItalianPizzaPoint("Екатеринбург", "ул. Сулимова, 31А"),
]


def resolve_italian_pizza_point(text: str) -> Optional[ItalianPizzaPoint]:
    lowered = (text or "").lower()
    best_point = None
    best_score = 0

    for point in ITALIAN_PIZZA_POINTS:
        score = 0
        city = point.city.lower()
        address = point.address.lower()

        if city in lowered:
            score += 2
        for token in city.replace(",", " ").split():
            if token and token in lowered:
                score += 1
        if address in lowered:
            score += 3
        for token in address.replace(",", " ").replace(".", " ").split():
            if len(token) >= 3 and token in lowered:
                score += 1

        if score > best_score:
            best_score = score
            best_point = point

    return best_point if best_score >= 2 else None


def build_stoplist_task(point_name: str) -> str:
    return (
        "Авторизуйся в личном кабинете Italian Pizza и собери актуальный стоп-лист "
        f"для точки «{point_name}».\n\n"
        "Нужно найти недоступные позиции именно для этой точки и вернуть короткий отчёт:\n"
        "1. Точка\n"
        "2. Список недоступных позиций\n"
        "3. Если доступна дата или время добавления в стоп-лист, укажи её\n"
        "4. Если позиций нет, так и напиши"
    )


def build_blanks_task(point_name: str) -> str:
    return (
        "Авторизуйся в личном кабинете Italian Pizza, выбери точку "
        f"«{point_name}» и открой раздел «Бланк загрузки».\n\n"
        "Нужно проверить наличие красных бланков и отклонений:\n"
        "1. Есть ли красные бланки\n"
        "2. Какие позиции или строки подсвечены красным\n"
        "3. Открыт или закрыт бланк\n"
        "4. Есть ли изменения лимита или отклонения от норматива\n"
        "Ответ верни кратко и по делу."
    )


def build_maps_reviews_task(point_name: str, user_message: str) -> str:
    return (
        f"Найди отзывы по точке «{point_name}» на картах и собери отчёт.\n\n"
        "Нужно:\n"
        "1. Найти именно эту точку\n"
        "2. Собрать отзывы за последние сутки, если пользователь просит этот период\n"
        "3. Выделить основные жалобы\n"
        "4. Выделить основные похвалы\n"
        "5. Дать короткий вывод по тональности\n\n"
        f"Исходный запрос пользователя: {user_message}"
    )
