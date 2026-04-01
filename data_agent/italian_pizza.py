from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


ITALIAN_PIZZA_PORTAL_URL = "https://tochka.italianpizza.ru/login"


@dataclass(frozen=True)
class ItalianPizzaPoint:
    city: str
    address: str
    public_slug: str

    @property
    def display_name(self) -> str:
        return f"{self.city}, {self.address}"

    @property
    def public_url(self) -> str:
        return f"https://{self.public_slug}.italianpizza.ru"


ITALIAN_PIZZA_POINTS = [
    ItalianPizzaPoint("Полевской", "Ленина 11", "polevskoi"),
    ItalianPizzaPoint("Асбест", "ТЦ Небо, Ленинградская 26/2", "asbest"),
    ItalianPizzaPoint("Сухой Лог", "Белинского 40", "slog"),
    ItalianPizzaPoint("Реж", "Ленина 17", "rezh"),
    ItalianPizzaPoint("Верхний Уфалей", "Ленина 147", "ufaley"),
    ItalianPizzaPoint("Артёмовский", "Гагарина 2а", "artemovsky"),
    ItalianPizzaPoint("Екатеринбург", "ул. Сулимова, 31А", "ekb"),
]


ALIASES = {
    "ленинградская 26": "ленинградская 26/2",
    "ленинградская, 26": "ленинградская 26/2",
    "небо ленинградская 26": "тц небо, ленинградская 26/2",
    "небо ленинградская 26/2": "тц небо, ленинградская 26/2",
    "сулимова 31а": "ул. сулимова, 31а",
    "ленина, 147": "ленина 147",
}


def resolve_italian_pizza_point(text: str) -> Optional[ItalianPizzaPoint]:
    lowered = (text or "").lower()
    for source, target in ALIASES.items():
        lowered = lowered.replace(source, target)

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
            score += 4
        for token in address.replace(",", " ").replace(".", " ").replace("/", " ").split():
            if len(token) >= 2 and token in lowered:
                score += 1

        if score > best_score:
            best_score = score
            best_point = point

    return best_point if best_score >= 2 else None


def build_stoplist_task(point_name: str) -> str:
    return (
        "Открой публичный сайт заказа Italian Pizza как обычный клиент и проверь недоступные позиции "
        f"для точки «{point_name}».\n\n"
        "Нужно:\n"
        "1. Выбрать нужную точку на публичном сайте\n"
        "2. Найти позиции, которые серые, disabled или недоступны для заказа\n"
        "3. Вернуть короткий отчёт со списком недоступных позиций\n"
        "4. Если недоступных позиций нет, так и напиши"
    )


def build_blanks_task(point_name: str, period_hint: str = "") -> str:
    period_line = f"\nПериод проверки: {period_hint}" if period_hint else ""
    return (
        "Авторизуйся в личном кабинете Italian Pizza, выбери точку "
        f"«{point_name}» и открой отчёт по перегрузкам / бланк загрузки.\n\n"
        "Нужно проверить:\n"
        "1. Есть ли красные бланки\n"
        "2. Какие позиции или строки подсвечены красным\n"
        "3. Открыт или закрыт бланк\n"
        "4. Есть ли изменения лимита или отклонения от норматива"
        f"{period_line}\n"
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
