from __future__ import annotations


def derive_webhook_url(
    raw_webhook_url: str | None,
    railway_public_domain: str | None,
    web_app_domain: str | None,
) -> str:
    webhook_url = (raw_webhook_url or "").strip().rstrip("/")
    if webhook_url and "your-domain.com" not in webhook_url:
        return webhook_url

    railway_domain = (railway_public_domain or "").strip()
    if railway_domain:
        return f"https://{railway_domain}".rstrip("/")

    app_domain = (web_app_domain or "").strip().rstrip("/")
    if app_domain.startswith("https://"):
        return app_domain

    return webhook_url or "https://your-domain.com"


def derive_internal_api_token(raw_token: str | None, bot_token: str | None) -> str:
    token = (raw_token or "").strip()
    if token and not token.startswith(("http://", "https://")):
        return token
    return (bot_token or "").strip()
