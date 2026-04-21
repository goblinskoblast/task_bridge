from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class SystemDescriptor:
    system_name: str
    title: str
    family: str
    entry_surface: str
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
)


_SYSTEM_CATALOG: dict[str, SystemDescriptor] = {
    "italian_pizza": SystemDescriptor(
        system_name="italian_pizza",
        title="Italian Pizza",
        family="restaurant_operations",
        entry_surface="web_portal",
        supports_scan=True,
        supports_points=True,
        supports_monitoring=True,
    ),
    "iiko": SystemDescriptor(
        system_name="iiko",
        title="iiko",
        family="restaurant_operations",
        entry_surface="web_portal",
        supports_scan=True,
        supports_points=True,
        supports_monitoring=True,
    ),
    "keeper": SystemDescriptor(
        system_name="keeper",
        title="Keeper",
        family="restaurant_operations",
        entry_surface="web_portal",
        supports_scan=True,
        supports_points=True,
        supports_monitoring=True,
    ),
    "rocketdata": SystemDescriptor(
        system_name="rocketdata",
        title="RocketData",
        family="restaurant_analytics",
        entry_surface="api_or_sheet",
        supports_monitoring=False,
    ),
    "1C": SystemDescriptor(
        system_name="1C",
        title="1C",
        family="backoffice",
        entry_surface="web_portal",
        supports_scan=True,
    ),
    "CRM": SystemDescriptor(
        system_name="CRM",
        title="CRM",
        family="crm",
        entry_surface="web_portal",
        supports_scan=True,
    ),
    "web-system": _DEFAULT_DESCRIPTOR,
    "telegram": SystemDescriptor(
        system_name="telegram",
        title="Telegram",
        family="messenger_channel",
        entry_surface="messenger",
        supports_chat_delivery=True,
    ),
    "max": SystemDescriptor(
        system_name="max",
        title="MAX",
        family="messenger_channel",
        entry_surface="messenger",
        supports_chat_delivery=True,
    ),
    "mobile-app": SystemDescriptor(
        system_name="mobile-app",
        title="TaskBridge App",
        family="first_party_surface",
        entry_surface="native_app",
        supports_chat_delivery=True,
    ),
    "messenger-agent": SystemDescriptor(
        system_name="messenger-agent",
        title="Messenger Account Agent",
        family="messenger_automation",
        entry_surface="account_agent",
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
