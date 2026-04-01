from __future__ import annotations

import logging
import re
from typing import List

from .browser_agent import browser_agent
from .italian_pizza import build_stoplist_task, resolve_italian_pizza_point

logger = logging.getLogger(__name__)

_CATEGORY_STOPWORDS = {
    "пицца",
    "комбо",
    "детское меню",
    "десерты",
    "напитки",
    "закуски",
    "салаты",
    "соусы",
    "роллы",
    "бургеры",
    "паста",
    "горячее",
    "супы",
    "войти",
    "контакты",
    "доставка",
    "заказать доставку",
    "выберите адрес",
    "меню",
}

_UNAVAILABLE_MARKERS = [
    "недоступ",
    "нет в наличии",
    "временно недоступ",
    "законч",
    "sold out",
    "unavailable",
]


class StoplistTool:
    def _clean_product_name(self, raw: str) -> str:
        lines = [line.strip() for line in (raw or "").splitlines() if line.strip()]
        filtered: list[str] = []
        for line in lines:
            lowered = line.lower()
            if lowered in _CATEGORY_STOPWORDS:
                continue
            if any(marker in lowered for marker in ["₽", "руб", "доставка", "войти", "контакты", "заказать"]):
                continue
            if len(line) < 3:
                continue
            filtered.append(line)

        if not filtered:
            return ""

        candidate = re.sub(r"\s+", " ", filtered[0]).strip(" -•")
        if candidate.lower() in _CATEGORY_STOPWORDS:
            return ""
        return candidate

    def _looks_like_unavailable_block(self, text: str) -> bool:
        lowered = (text or "").lower()
        return any(marker in lowered for marker in _UNAVAILABLE_MARKERS)

    def _looks_like_good_stoplist(self, items: List[str]) -> bool:
        meaningful = 0
        for item in items:
            lowered = item.lower()
            if lowered in _CATEGORY_STOPWORDS:
                continue
            if len(item) < 4:
                continue
            meaningful += 1
        return meaningful >= 2

    async def _select_public_point(self, page, point) -> None:
        trigger_candidates = ["Выберите адрес", point.city]
        for candidate in trigger_candidates:
            locator = page.locator(f"text={candidate}")
            if await locator.count() > 0:
                try:
                    await locator.first.click(timeout=3000)
                    await page.wait_for_timeout(1500)
                    logger.info("Stoplist opened address selector via=%s", candidate)
                    break
                except Exception:
                    continue

        address_candidates = [point.address, point.display_name, point.city]
        for candidate in address_candidates:
            locator = page.locator(f"text={candidate}")
            if await locator.count() > 0:
                try:
                    await locator.first.click(timeout=3000)
                    await page.wait_for_timeout(1800)
                    logger.info("Stoplist selected point via=%s", candidate)
                    return
                except Exception:
                    continue

        logger.info("Stoplist point selector not confirmed for=%s", point.display_name)

    async def _collect_public_stoplist_dom(self, point_name: str) -> str:
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
                target_url = point.public_url.rstrip("/") + "/"
                logger.info("Stoplist public browser run point=%s url=%s", point.display_name, target_url)
                await page.goto(target_url, wait_until="domcontentloaded", timeout=25000)
                await page.wait_for_timeout(2500)

                await self._select_public_point(page, point)

                product_candidates: list[str] = []
                card_selectors = [
                    "[data-testid*='product']",
                    "[data-qa*='product']",
                    "[class*='product']",
                    "[class*='item']",
                    "[class*='card']",
                    "article",
                    "li",
                ]
                for selector in card_selectors:
                    locator = page.locator(selector)
                    count = min(await locator.count(), 160)
                    logger.info("Stoplist selector=%s count=%s", selector, count)
                    for index in range(count):
                        try:
                            block = locator.nth(index)
                            text = (await block.inner_text()).strip()
                            if not text or len(text) > 500:
                                continue

                            class_name = (await block.get_attribute("class") or "").lower()
                            aria_disabled = (await block.get_attribute("aria-disabled") or "").lower()
                            disabled_attr = await block.get_attribute("disabled")
                            style_attr = (await block.get_attribute("style") or "").lower()
                            unavailable = (
                                self._looks_like_unavailable_block(text)
                                or "disabled" in class_name
                                or "unavailable" in class_name
                                or aria_disabled == "true"
                                or disabled_attr is not None
                                or "opacity" in style_attr
                                or "grayscale" in style_attr
                            )
                            if not unavailable:
                                continue

                            product_name = self._clean_product_name(text)
                            if not product_name:
                                continue
                            if product_name not in product_candidates:
                                product_candidates.append(product_name)
                        except Exception:
                            continue

                logger.info("Stoplist DOM candidates point=%s items=%s", point.display_name, product_candidates[:20])
                if self._looks_like_good_stoplist(product_candidates):
                    return f"Точка: {point.display_name}\nСтоп-лист:\n" + "\n".join(f"- {item}" for item in product_candidates[:40])

                body = (await page.locator("body").inner_text())[:4000]
                unavailable_lines: List[str] = []
                for line in body.splitlines():
                    clean = line.strip()
                    if not clean:
                        continue
                    lowered = clean.lower()
                    if self._looks_like_unavailable_block(lowered):
                        unavailable_lines.append(clean)
                if unavailable_lines:
                    preview = "\n".join(unavailable_lines[:20])
                    return f"Точка: {point.display_name}\nНайдены признаки стоп-листа, но нужен более точный DOM-разбор:\n{preview}"
                return f"Точка: {point.display_name}\nСтатус: недоступных позиций на публичном сайте не найдено."
            finally:
                await context.close()
                await browser.close()

    async def _collect_public_stoplist_ai(self, point_name: str) -> str:
        point = resolve_italian_pizza_point(point_name)
        if not point:
            return f"Не удалось определить публичную точку для стоп-листа: {point_name}"

        task = (
            build_stoplist_task(point.display_name)
            + "\n\nСначала обязательно открой выбор адреса и выбери нужную точку. "
              "Нельзя завершать задачу на первом экране, если на странице виден текст 'Выберите адрес'. "
              "После выбора точки просмотри карточки товаров и верни только реальные недоступные товары. "
              "Не перечисляй категории меню, кнопки, баннеры, заголовки и служебные элементы. "
              "Если не можешь подтвердить товар как недоступный, не включай его в ответ."
        )
        logger.info("Stoplist AI fallback point=%s url=%s", point.display_name, point.public_url)
        data = await browser_agent.extract_data(
            url=point.public_url,
            username=None,
            encrypted_password=None,
            user_task=task,
            progress_callback=None,
        )
        return f"Точка: {point.display_name}\nСтоп-лист:\n{data}"

    async def collect_for_point(
        self,
        *,
        url: str,
        username: str,
        encrypted_password: str,
        point_name: str,
    ) -> dict:
        report_text = await self._collect_public_stoplist_dom(point_name)
        if "Стоп-лист:" not in report_text or "недоступных позиций на публичном сайте не найдено" in report_text:
            logger.info("Stoplist DOM result weak for point=%s, using AI fallback", point_name)
            try:
                report_text = await self._collect_public_stoplist_ai(point_name)
            except Exception as exc:
                logger.warning("Stoplist AI fallback failed point=%s error=%s", point_name, exc)
        return {
            "status": "ok",
            "point_name": point_name,
            "report_text": report_text,
        }


stoplist_tool = StoplistTool()
