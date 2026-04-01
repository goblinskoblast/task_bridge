from __future__ import annotations

import hashlib
import re

from email_integration.encryption import decrypt_password


class BlanksTool:
    async def _select_period(self, page, period_hint: str) -> None:
        if not period_hint:
            return

        lowered = period_hint.lower()
        candidates: list[str] = []
        if "3 часа" in lowered:
            candidates = ["3 часа", "3ч", "За 3 часа", "Последние 3 часа"]
        elif "сутки" in lowered:
            candidates = ["Сутки", "24 часа", "За сутки", "Последние сутки"]
        elif "сегодня" in lowered:
            candidates = ["Сегодня"]

        for candidate in candidates:
            locator = page.locator(f"text={candidate}")
            if await locator.count() > 0:
                try:
                    await locator.first.click(timeout=3000)
                    await page.wait_for_timeout(1500)
                    return
                except Exception:
                    continue

    async def _collect_portal_blanks(
        self,
        url: str,
        username: str,
        encrypted_password: str,
        point_name: str,
        period_hint: str,
    ) -> str:
        password = decrypt_password(encrypted_password) if encrypted_password else ""
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError("Playwright is not installed") from exc

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context(locale="ru-RU", timezone_id="Europe/Moscow")
            page = await context.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(1200)

                username_candidates = [
                    "input[name='username']",
                    "input[name='login']",
                    "input[type='email']",
                ]
                password_candidates = [
                    "input[type='password']",
                    "input[name='password']",
                ]
                submit_candidates = [
                    "button[type='submit']",
                    "button:has-text('Войти')",
                    "button:has-text('Login')",
                ]

                for selector in username_candidates:
                    if await page.locator(selector).count() > 0:
                        await page.fill(selector, username)
                        break
                for selector in password_candidates:
                    if await page.locator(selector).count() > 0:
                        await page.fill(selector, password)
                        break
                for selector in submit_candidates:
                    if await page.locator(selector).count() > 0:
                        await page.locator(selector).first.click()
                        break
                await page.wait_for_timeout(1800)

                point_candidates = [point_name, point_name.split(",")[0], point_name.split(",")[-1].strip()]
                for candidate in point_candidates:
                    locator = page.locator(f"text={candidate}")
                    if await locator.count() > 0:
                        try:
                            await locator.first.click(timeout=3000)
                            await page.wait_for_timeout(1500)
                            break
                        except Exception:
                            continue

                for candidate in ["Отчеты", "Отчёты", "Отчет по перегрузкам", "Отчёт по перегрузкам", "Перегрузки", "Бланк загрузки"]:
                    locator = page.locator(f"text={candidate}")
                    if await locator.count() > 0:
                        try:
                            await locator.first.click(timeout=3000)
                            await page.wait_for_timeout(1500)
                        except Exception:
                            continue

                await self._select_period(page, period_hint)

                body = (await page.locator("body").inner_text())[:8000]
                if period_hint:
                    body = f"Период: {period_hint}\n{body}"
                return body
            finally:
                await context.close()
                await browser.close()

    def _normalize_report(self, point_name: str, data: str) -> tuple[str, bool]:
        raw = (data or "").strip()
        if not raw:
            return (
                f"Точка: {point_name}\nПроверка бланков не дала результата. Нужен повторный запуск.",
                False,
            )

        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        filtered: list[str] = []
        for line in lines:
            lowered = line.lower()
            if any(marker in lowered for marker in ["cookie", "войти", "login", "пароль", "скачать приложение"]):
                continue
            filtered.append(line)

        signal_lines: list[str] = []
        for line in filtered:
            lowered = line.lower()
            if any(marker in lowered for marker in ["красн", "перегруз", "отклон", "лимит", "норматив", "закрыт", "открыт"]):
                signal_lines.append(line)

        body = "\n".join(signal_lines[:20]).strip()
        if not body:
            body = "\n".join(filtered[:60]).strip() or raw[:3500]

        has_red_flags = bool(re.search(r"красн|red|ошиб|отклон|лимит|закрыт|перегруз", body, flags=re.IGNORECASE))
        status_line = "найдены красные бланки или отклонения" if has_red_flags else "красных бланков не найдено"
        return f"Точка: {point_name}\nСтатус: {status_line}\n{body}", has_red_flags

    async def inspect_point(
        self,
        *,
        url: str,
        username: str,
        encrypted_password: str,
        point_name: str,
        period_hint: str = "",
    ) -> dict:
        data = await self._collect_portal_blanks(url, username, encrypted_password, point_name, period_hint)
        report_text, has_red_flags = self._normalize_report(point_name, data)
        alert_hash = hashlib.sha256(report_text.encode("utf-8", errors="ignore")).hexdigest()
        return {
            "status": "ok",
            "point_name": point_name,
            "has_red_flags": has_red_flags,
            "alert_hash": alert_hash,
            "report_text": report_text,
            "period_hint": period_hint or "текущий бланк",
        }


blanks_tool = BlanksTool()
