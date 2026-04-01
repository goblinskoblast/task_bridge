from __future__ import annotations

from typing import List

from .italian_pizza import resolve_italian_pizza_point


class StoplistTool:
    async def _collect_public_stoplist(self, point_name: str) -> str:
        point = resolve_italian_pizza_point(point_name)
        if not point:
            return f"Не удалось определить публичную точку для стоп-листа: {point_name}"

        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError("Playwright is not installed") from exc

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context(locale="ru-RU", timezone_id="Europe/Moscow")
            page = await context.new_page()
            try:
                await page.goto(point.public_url, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(2000)

                for candidate in [point.address, point.display_name, point.city, "Выберите адрес"]:
                    locator = page.locator(f"text={candidate}")
                    if await locator.count() > 0:
                        try:
                            await locator.first.click(timeout=3000)
                            await page.wait_for_timeout(1500)
                        except Exception:
                            continue

                unavailable_selectors = [
                    "[disabled]",
                    "[aria-disabled='true']",
                    "[class*='disabled']",
                    "[class*='disable']",
                    "[class*='unavailable']",
                    "text=Недоступно",
                ]

                items: List[str] = []
                for selector in unavailable_selectors:
                    locator = page.locator(selector)
                    count = min(await locator.count(), 40)
                    for index in range(count):
                        try:
                            text = (await locator.nth(index).inner_text()).strip()
                            if text and text not in items and len(text) <= 200:
                                items.append(text)
                        except Exception:
                            continue

                if not items:
                    body = (await page.locator("body").inner_text())[:2500]
                    if "недоступ" in body.lower() or "законч" in body.lower():
                        return f"Точка: {point.display_name}\nНа странице есть признаки недоступных позиций, но нужен более точный DOM-разбор.\n\n{body}"
                    return f"Точка: {point.display_name}\nСтатус: недоступных позиций на публичном сайте не найдено."

                return f"Точка: {point.display_name}\nСтоп-лист:\n" + "\n".join(f"- {item}" for item in items[:30])
            finally:
                await context.close()
                await browser.close()

    async def collect_for_point(
        self,
        *,
        url: str,
        username: str,
        encrypted_password: str,
        point_name: str,
    ) -> dict:
        report_text = await self._collect_public_stoplist(point_name)
        return {
            "status": "ok",
            "point_name": point_name,
            "report_text": report_text,
        }


stoplist_tool = StoplistTool()
