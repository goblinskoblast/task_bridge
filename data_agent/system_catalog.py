from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class SystemDescriptor:
    system_name: str
    title: str
    family: str
    entry_surface: str
    point_entity_label: str = "точка"
    scan_order: tuple[str, ...] = ()
    report_entry_labels: tuple[str, ...] = ()
    monitor_targets: tuple[str, ...] = ()
    primary_entities: tuple[str, ...] = ()
    reliability_policy: tuple[str, ...] = ()
    auth_mode: str = "login_password"
    product_stage: str = "scaffold"
    next_step_hint: str = ""
    supports_scan: bool = False
    supports_points: bool = False
    supports_monitoring: bool = False
    supports_chat_delivery: bool = False
    supports_account_agent: bool = False


_DEFAULT_DESCRIPTOR = SystemDescriptor(
    system_name="web-system",
    title="Web System",
    family="generic_web",
    entry_surface="web_portal",
    scan_order=("логин", "первичная навигация", "поиск ключевых разделов"),
    primary_entities=("системные разделы", "точки / объекты", "отчёты"),
    reliability_policy=("сначала читаем и картируем разделы", "без боевых действий до понятного scan"),
    auth_mode="login_password",
    product_stage="scaffold",
    next_step_hint="Следом нужен scan структуры системы, чтобы понять точки, отчёты и рабочие разделы.",
)


_SYSTEM_CATALOG: dict[str, SystemDescriptor] = {
    "italian_pizza": SystemDescriptor(
        system_name="italian_pizza",
        title="Italian Pizza",
        family="restaurant_operations",
        entry_surface="web_portal",
        point_entity_label="точка продаж",
        scan_order=("логин", "выбрать точку", "отчёты", "мониторинг"),
        report_entry_labels=("Стоп-Лист", "Бланк загрузки", "Отчёты"),
        monitor_targets=("stoplist", "blanks"),
        primary_entities=("точка продаж", "стоп-лист", "бланки", "отчёты"),
        reliability_policy=(
            "читаем данные в read-only логике",
            "жёлтые blanks не считаем красной зоной",
            "алертим только по подтверждённым красным сигналам",
        ),
        auth_mode="login_password",
        product_stage="production",
        next_step_hint="Дальше можно добавить точку и сразу работать со stoplist и blanks обычным сообщением.",
        supports_scan=True,
        supports_points=True,
        supports_monitoring=True,
    ),
    "iiko": SystemDescriptor(
        system_name="iiko",
        title="iiko",
        family="restaurant_operations",
        entry_surface="web_portal",
        point_entity_label="ресторан / точка",
        scan_order=("логин", "организация", "точки", "отчёты / операционные разделы"),
        report_entry_labels=("организации", "точки", "отчёты", "доставка", "склад"),
        monitor_targets=("availability", "menu_status", "operations"),
        primary_entities=("организация", "ресторан / точка", "доставка", "склад", "отчёты"),
        reliability_policy=(
            "сначала строим карту разделов и сущностей",
            "не выполняем боевые действия до понятного scan",
            "мониторинг включаем только после привязки точки",
        ),
        auth_mode="sso_web",
        product_stage="scaffold",
        next_step_hint="Следом нужен scan структуры iiko и карта сущностей: точки, отчёты, доставка, склад.",
        supports_scan=True,
        supports_points=True,
        supports_monitoring=True,
    ),
    "keeper": SystemDescriptor(
        system_name="keeper",
        title="Keeper",
        family="restaurant_operations",
        entry_surface="web_portal",
        point_entity_label="ресторан / объект",
        scan_order=("логин", "объект", "операционные разделы", "отчёты"),
        report_entry_labels=("объекты", "кассы", "отчёты", "меню"),
        monitor_targets=("availability", "menu_status", "operations"),
        primary_entities=("ресторан / объект", "кассы", "меню", "отчёты"),
        reliability_policy=(
            "сначала собираем карту объектов и отчётных входов",
            "без автоматических действий до понятного scan",
            "сигналы привязываем к конкретному объекту",
        ),
        auth_mode="web_login",
        product_stage="scaffold",
        next_step_hint="Следом нужен scan структуры Keeper и карта объектов, меню и отчётных разделов.",
        supports_scan=True,
        supports_points=True,
        supports_monitoring=True,
    ),
    "rocketdata": SystemDescriptor(
        system_name="rocketdata",
        title="RocketData",
        family="restaurant_analytics",
        entry_surface="api_or_sheet",
        point_entity_label="карточка / локация",
        scan_order=("авторизация", "источник отзывов", "локации", "аналитика"),
        report_entry_labels=("отзывы", "рейтинги", "площадки"),
        primary_entities=("локация", "отзывы", "рейтинги", "площадки"),
        reliability_policy=(
            "начинаем с маппинга локаций и источников",
            "аналитику собираем пока без боевой автоматизации",
        ),
        auth_mode="api_or_sheet",
        product_stage="scaffold",
        next_step_hint="Дальше можно собирать отзывы и аналитику по локациям.",
        supports_monitoring=False,
    ),
    "1C": SystemDescriptor(
        system_name="1C",
        title="1C",
        family="backoffice",
        entry_surface="web_portal",
        point_entity_label="объект",
        scan_order=("логин", "разделы учёта", "объекты", "отчёты"),
        primary_entities=("объект", "учётный раздел", "отчёт"),
        reliability_policy=("сначала читаем конфигурацию и сущности", "без изменений до ясной карты 1C"),
        auth_mode="web_login",
        product_stage="planned",
        next_step_hint="Следом нужен scan рабочей конфигурации и сущностей учёта.",
        supports_scan=True,
    ),
    "CRM": SystemDescriptor(
        system_name="CRM",
        title="CRM",
        family="crm",
        entry_surface="web_portal",
        point_entity_label="клиент / объект",
        scan_order=("логин", "воронки / объекты", "карточки", "действия"),
        primary_entities=("клиент", "объект", "карточка", "действие"),
        reliability_policy=("сначала делаем scan CRM-сущностей", "автодействия отделяем от read-only обзора"),
        auth_mode="web_login",
        product_stage="planned",
        next_step_hint="Следом нужен scan CRM-сущностей и рабочих карточек.",
        supports_scan=True,
    ),
    "web-system": _DEFAULT_DESCRIPTOR,
    "telegram": SystemDescriptor(
        system_name="telegram",
        title="Telegram",
        family="messenger_channel",
        entry_surface="messenger",
        point_entity_label="чат",
        scan_order=("чат", "сценарии бота", "доставка", "реакции"),
        primary_entities=("чат", "диалог", "отчёт", "alert"),
        reliability_policy=("быстрый ack для длинных запросов", "free-text-first UX без лишней внутренней кухни"),
        auth_mode="bot_channel",
        product_stage="production",
        next_step_hint="Канал уже боевой: держим parity UX и прозрачную доставку.",
        supports_chat_delivery=True,
    ),
    "max": SystemDescriptor(
        system_name="max",
        title="MAX",
        family="messenger_channel",
        entry_surface="messenger",
        point_entity_label="чат",
        scan_order=("чат", "сценарии бота", "доставка", "реакции"),
        primary_entities=("чат", "диалог", "отчёт", "alert"),
        reliability_policy=("держим parity с Telegram по UX-контракту", "начинаем с read-only и прозрачной доставки"),
        auth_mode="messenger_channel",
        product_stage="planned",
        next_step_hint="Следом нужен parity-контур с Telegram: тот же free-text-first UX и те же продуктовые сценарии.",
        supports_chat_delivery=True,
    ),
    "mobile-app": SystemDescriptor(
        system_name="mobile-app",
        title="TaskBridge App",
        family="first_party_surface",
        entry_surface="native_app",
        point_entity_label="рабочая поверхность",
        scan_order=("вход", "рабочий обзор", "точки", "alerts"),
        primary_entities=("дашборд", "точки", "alerts", "настройки"),
        reliability_policy=("оставляем единый UX-контракт с Telegram", "не прячем критичные сигналы в лишней навигации"),
        auth_mode="taskbridge_auth",
        product_stage="planned",
        next_step_hint="Позже app станет first-party поверхностью для обзора, настройки и аналитики.",
        supports_chat_delivery=True,
    ),
    "messenger-agent": SystemDescriptor(
        system_name="messenger-agent",
        title="Messenger Account Agent",
        family="messenger_automation",
        entry_surface="account_agent",
        point_entity_label="аккаунт / чат",
        scan_order=("авторизация", "контур аккаунта", "чаты", "действия агента"),
        primary_entities=("аккаунт", "чат", "сообщение", "действие агента"),
        reliability_policy=(
            "нужна trust-модель и audit trail",
            "автодействия только с явными границами и историей",
        ),
        auth_mode="account_session",
        product_stage="planned",
        next_step_hint="Этот слой идёт позже: сначала нужны trust-модель, audit trail и границы действий.",
        supports_chat_delivery=True,
        supports_account_agent=True,
    ),
}


_SYSTEM_ALIASES: dict[str, str] = {
    "italianpizza": "italian_pizza",
    "italian_pizza": "italian_pizza",
    "iiko": "iiko",
    "keeper": "keeper",
    "rkeeper": "keeper",
    "rocketdata": "rocketdata",
    "1c": "1C",
    "1с": "1C",
    "crm": "CRM",
    "web-system": "web-system",
    "web_system": "web-system",
    "telegram": "telegram",
    "max": "max",
    "mobile-app": "mobile-app",
    "mobile_app": "mobile-app",
    "messenger-agent": "messenger-agent",
    "messenger_agent": "messenger-agent",
}


_URL_RULES: tuple[tuple[str, str], ...] = (
    ("tochka.italianpizza", "italian_pizza"),
    ("italianpizza", "italian_pizza"),
    ("iiko", "iiko"),
    ("rkeeper", "keeper"),
    ("keeper", "keeper"),
    ("rocketdata", "rocketdata"),
    ("1c", "1C"),
    ("crm", "CRM"),
)


def normalize_system_name(system_name: str | None) -> str:
    normalized = str(system_name or "").strip().lower().replace("_", "-")
    return _SYSTEM_ALIASES.get(normalized, str(system_name or "").strip() or _DEFAULT_DESCRIPTOR.system_name)


def detect_system_name_from_url(url: str | None) -> str:
    if not url:
        return _DEFAULT_DESCRIPTOR.system_name
    host = urlparse(url).netloc.lower()
    path = urlparse(url).path.lower()
    probe = f"{host}{path}"
    for marker, system_name in _URL_RULES:
        if marker in probe:
            return system_name
    return _DEFAULT_DESCRIPTOR.system_name


def resolve_system_descriptor(*, system_name: str | None = None, url: str | None = None) -> SystemDescriptor:
    normalized_name = normalize_system_name(system_name) if system_name else ""
    detected_name = detect_system_name_from_url(url)

    if detected_name != _DEFAULT_DESCRIPTOR.system_name:
        return _SYSTEM_CATALOG.get(detected_name, _DEFAULT_DESCRIPTOR)
    if normalized_name:
        return _SYSTEM_CATALOG.get(normalized_name, _DEFAULT_DESCRIPTOR)
    return _DEFAULT_DESCRIPTOR


def is_italian_pizza_descriptor(*, system_name: str | None = None, url: str | None = None) -> bool:
    return resolve_system_descriptor(system_name=system_name, url=url).system_name == "italian_pizza"


def capability_labels(descriptor: SystemDescriptor) -> list[str]:
    labels: list[str] = []
    if descriptor.supports_scan:
        labels.append("scan")
    if descriptor.supports_points:
        labels.append("точки")
    if descriptor.supports_monitoring:
        labels.append("мониторинг")
    if descriptor.supports_chat_delivery:
        labels.append("доставка в чат")
    if descriptor.supports_account_agent:
        labels.append("account agent")
    return labels


def orientation_summary(descriptor: SystemDescriptor) -> str | None:
    if not descriptor.scan_order:
        return None
    return " -> ".join(descriptor.scan_order)


def report_sections(descriptor: SystemDescriptor) -> list[str]:
    return [item for item in descriptor.report_entry_labels if item]


def monitor_signal_labels(descriptor: SystemDescriptor) -> list[str]:
    labels = {
        "availability": "доступность",
        "menu_status": "меню",
        "operations": "операционка",
        "stoplist": "стоп-лист",
        "blanks": "бланки",
        "reviews": "отзывы",
    }
    return [labels.get(item, item) for item in descriptor.monitor_targets if item]


def system_family_label(family: str | None) -> str:
    labels = {
        "restaurant_operations": "ресторанная операционка",
        "restaurant_analytics": "репутация и аналитика",
        "generic_web": "универсальный web-контур",
        "messenger_channel": "клиентский канал",
        "messenger_automation": "автоматизация мессенджеров",
        "first_party_surface": "собственная поверхность",
        "backoffice": "бэк-офис",
        "crm": "CRM-контур",
    }
    return labels.get(str(family or ""), "внешняя система")


def entry_surface_label(surface: str | None) -> str:
    labels = {
        "web_portal": "web portal",
        "api_or_sheet": "api / sheet",
        "messenger": "messenger",
        "native_app": "native app",
        "account_agent": "account agent",
    }
    return labels.get(str(surface or ""), "surface")


def auth_mode_label(auth_mode: str | None) -> str:
    labels = {
        "login_password": "логин + пароль",
        "sso_web": "web SSO",
        "web_login": "web-авторизация",
        "api_or_sheet": "api / sheet",
        "bot_channel": "бот-канал",
        "messenger_channel": "канал мессенджера",
        "taskbridge_auth": "TaskBridge auth",
        "account_session": "аккаунт-сессия",
    }
    return labels.get(str(auth_mode or ""), "auth")


def product_stage_label(stage: str | None) -> str:
    labels = {
        "production": "боевой контур",
        "scaffold": "каркас / scan-first",
        "planned": "запланировано",
    }
    return labels.get(str(stage or ""), "стадия не уточнена")


def build_scan_contract_payload(descriptor: SystemDescriptor) -> dict[str, object]:
    return {
        "stage": descriptor.product_stage,
        "stage_label": product_stage_label(descriptor.product_stage),
        "auth_mode": descriptor.auth_mode,
        "auth_mode_label": auth_mode_label(descriptor.auth_mode),
        "primary_entities": [item for item in descriptor.primary_entities if item],
        "report_sections": report_sections(descriptor),
        "monitor_signals": monitor_signal_labels(descriptor),
        "reliability_policy": [item for item in descriptor.reliability_policy if item],
    }
