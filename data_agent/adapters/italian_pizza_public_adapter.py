from __future__ import annotations

import logging
import re

from ..italian_pizza import resolve_italian_pizza_point

logger = logging.getLogger(__name__)

_CATEGORY_STOPWORDS = {
    "пицца", "комбо", "детское меню", "десерты", "напитки", "закуски", "салаты", "соусы",
    "роллы", "бургеры", "паста", "горячее", "супы", "войти", "контакты", "доставка",
    "заказать доставку", "выберите адрес", "меню", "фильтры", "еще",
}


class ItalianPizzaPublicAdapter:
    def _detect_public_page_issue(self, text: str) -> str | None:
        lowered = re.sub(r"\s+", " ", (text or "").lower()).strip()
        if not lowered:
            return None
        if any(token in lowered for token in ["captcha", "капча", "я не робот", "i am not a robot"]):
            return "Публичный сайт запросил captcha."
        if any(token in lowered for token in ["нет доступа", "access denied", "403", "forbidden"]):
            return "Публичный сайт вернул отказ в доступе."
        if any(token in lowered for token in ["технические работы", "временно недоступен", "service unavailable", "502", "503", "504"]):
            return "Публичный сайт временно недоступен."
        return None

    def _build_failed_result(self, point_name: str, issue_text: str) -> dict:
        report_text = f"Точка: {point_name}\nСтатус: {issue_text}"
        return {
            "status": "failed",
            "point_name": point_name,
            "selected": False,
            "report_text": report_text,
            "message": issue_text,
            "alert_hash": None,
        }

    def _looks_like_order_action(self, text: str) -> bool:
        lowered = re.sub(r"\s+", " ", (text or "").lower()).strip()
        if not lowered:
            return False
        action_markers = ["выбрать", "в корзину", "добавить", "заказать", "недоступно"]
        return any(marker in lowered for marker in action_markers)

    def _clean_product_name(self, raw: str) -> str:
        lines = [line.strip() for line in (raw or "").splitlines() if line.strip()]
        filtered: list[str] = []
        for line in lines:
            lowered = line.lower()
            if lowered in _CATEGORY_STOPWORDS:
                continue
            if any(marker in lowered for marker in ["₽", "руб", "доставка", "войти", "контакты", "заказать", " г", " кг"]):
                continue
            if len(line) < 3:
                continue
            filtered.append(line)
        if not filtered:
            return ""
        candidate = re.sub(r"\s+", " ", filtered[0]).strip(" -•")
        lowered = candidate.lower()
        if lowered in _CATEGORY_STOPWORDS:
            return ""
        if any(lowered.startswith(prefix) for prefix in ["заказ по телефону", "франшиза", "акции"]):
            return ""
        return candidate

    async def _dismiss_common_overlays(self, page) -> bool:
        selectors = [
            "button:has-text('Принять')",
            "button:has-text('Accept')",
            "button:has-text('Понятно')",
            "button:has-text('Закрыть')",
            "[role='button']:has-text('Принять')",
            "[role='button']:has-text('Accept')",
        ]
        for selector in selectors:
            locator = page.locator(selector)
            try:
                if await locator.count() == 0:
                    continue
                await locator.first.click(timeout=2000)
                await page.wait_for_timeout(700)
                logger.info("Stoplist overlay dismissed selector=%s", selector)
                return True
            except Exception:
                continue
        return False

    async def _open_address_modal(self, page, point) -> None:
        for candidate in ["Выберите адрес", point.city]:
            locator = page.locator(f"text={candidate}")
            if await locator.count() > 0:
                try:
                    await locator.first.click(timeout=3000)
                    await page.wait_for_timeout(1200)
                    logger.info("Stoplist opened address selector via=%s", candidate)
                    return
                except Exception:
                    continue

    async def _set_delivery_mode(self, page) -> None:
        locator = page.locator("text=Доставка")
        if await locator.count() > 0:
            try:
                await locator.first.click(timeout=2000)
                await page.wait_for_timeout(700)
                logger.info("Stoplist address mode clicked=Доставка")
            except Exception:
                pass

    async def _iter_text_candidates(self, page, selector: str, max_items: int = 160) -> list[tuple[int, str]]:
        locator = page.locator(selector)
        count = min(await locator.count(), max_items)
        results: list[tuple[int, str]] = []
        for idx in range(count):
            item = locator.nth(idx)
            try:
                if not await item.is_visible():
                    continue
                text = (await item.inner_text()).strip()
            except Exception:
                continue
            if not text or len(text) > 140:
                continue
            normalized = re.sub(r"\s+", " ", text)
            results.append((idx, normalized))
        return results

    async def _collect_suggestion_candidates(self, page, query: str) -> list[str]:
        street = query.split()[0].lower()
        number_tokens = [token.lower() for token in query.split() if any(ch.isdigit() for ch in token)]
        candidates: list[str] = []
        for _, text in await self._iter_text_candidates(page, "button, [role='option'], [role='button'], li, div, span"):
            lowered = text.lower()
            if lowered in {"доставка", "самовывоз"} or "выберите адрес" in lowered:
                continue
            if street and street not in lowered and not any(token in lowered for token in number_tokens):
                continue
            if text not in candidates:
                candidates.append(text)
        return candidates[:30]

    async def _click_suggestion(self, page, query: str) -> bool:
        street = query.split()[0].lower()
        tail = query.lower()
        number_tokens = [token.lower() for token in query.split() if any(ch.isdigit() for ch in token)]
        locator = page.locator("button, [role='option'], [role='button'], li, div, span")
        count = min(await locator.count(), 180)
        best_idx = None
        best_text = ""
        best_score = 0
        for idx in range(count):
            item = locator.nth(idx)
            try:
                if not await item.is_visible():
                    continue
                text = re.sub(r"\s+", " ", (await item.inner_text()).strip())
            except Exception:
                continue
            if not text or len(text) > 140:
                continue
            lowered = text.lower()
            if lowered in {"доставка", "самовывоз"} or "выберите адрес" in lowered:
                continue
            score = 0
            if tail and tail in lowered:
                score += 10
            if street and street in lowered:
                score += 4
            for token in number_tokens:
                if token in lowered:
                    score += 6
            if score > best_score:
                best_idx = idx
                best_text = text
                best_score = score
        if best_idx is None or best_score < 8:
            logger.info("Stoplist suggestion click result=%s", {"clicked": False, "score": best_score, "text": best_text})
            return False
        try:
            await locator.nth(best_idx).click(timeout=2500)
            logger.info("Stoplist suggestion click result=%s", {"clicked": True, "score": best_score, "text": best_text})
            return True
        except Exception as exc:
            logger.info("Stoplist suggestion click failed index=%s text=%s error=%s", best_idx, best_text, exc)
            return False

    async def _fill_address(self, page, point) -> bool:
        query = point.address.split(",")[-1].strip() or point.address
        selectors = [
            "input[placeholder*='Введите адрес']",
            "input[aria-label*='адрес']",
            "input[name*='address']",
            "input[placeholder*='адрес']",
            "input[type='text']",
        ]
        for selector in selectors:
            locator = page.locator(selector)
            count = await locator.count()
            for idx in range(count):
                field = locator.nth(idx)
                try:
                    if not await field.is_visible():
                        continue
                    await field.click()
                    await field.fill("")
                    await field.fill(query)
                    await page.wait_for_timeout(1200)
                    logger.info("Stoplist filled address input selector=%s index=%s value=%s", selector, idx, query)
                    suggestion_candidates = await self._collect_suggestion_candidates(page, query)
                    logger.info("Stoplist suggestion candidates=%s", suggestion_candidates)
                    if await self._click_suggestion(page, query):
                        await page.wait_for_timeout(1500)
                        return True
                    await field.press("ArrowDown")
                    await page.wait_for_timeout(500)
                    await field.press("Enter")
                    await page.wait_for_timeout(1500)
                    logger.info("Stoplist used keyboard suggestion flow selector=%s index=%s", selector, idx)
                    return True
                except Exception as exc:
                    logger.info("Stoplist address input failed selector=%s index=%s error=%s", selector, idx, exc)
        return False

    async def _confirm_selected_point(self, page, point) -> bool:
        body_text = await page.locator("body").inner_text()
        page_text = re.sub(r"\s+", " ", body_text.lower()).strip()
        tail = point.address.split(",")[-1].strip().lower()
        if tail and tail in page_text:
            logger.info("Stoplist inferred point selection by page text address=%s", point.address)
            return True
        if "выберите адрес" not in page_text and point.city.lower() in page_text:
            logger.info("Stoplist inferred point selection by closed modal city=%s", point.city)
            return True
        logger.info("Stoplist point selector not confirmed for=%s", point.display_name)
        return False

    async def _scroll_all(self, page) -> None:
        for _ in range(10):
            try:
                await page.mouse.wheel(0, 1800)
            except Exception:
                await page.evaluate("window.scrollBy(0, 1800)")
            await page.wait_for_timeout(600)

    async def _is_disabled_button(self, btn) -> bool:
        try:
            disabled_attr = await btn.get_attribute("disabled")
            aria_disabled = await btn.get_attribute("aria-disabled")
            classes = (await btn.get_attribute("class") or "").lower()
            if disabled_attr is not None or aria_disabled == "true":
                return True
            if any(token in classes for token in ["disabled", "unavailable", "gray"]):
                return True
            if not await btn.is_enabled():
                return True
            try:
                await btn.click(trial=True, timeout=800)
                return False
            except Exception:
                return True
        except Exception:
            return False

    async def _extract_card_text(self, btn) -> str:
        xpaths = [
            "xpath=ancestor::article[1]",
            "xpath=ancestor::li[1]",
            "xpath=ancestor::*[contains(@class,'item')][1]",
            "xpath=ancestor::*[contains(@class,'card')][1]",
            "xpath=ancestor::*[contains(@class,'product')][1]",
            "xpath=ancestor::div[1]",
        ]
        for xpath in xpaths:
            locator = btn.locator(xpath)
            try:
                if await locator.count() == 0:
                    continue
                text = (await locator.first.inner_text()).strip()
                if text and len(text) > 2:
                    return text
            except Exception:
                continue
        return ""

    async def _collect_disabled_products(self, page) -> list[str]:
        results: list[str] = []
        locator = page.locator("button, [role='button'], a")
        count = min(await locator.count(), 220)
        for idx in range(count):
            btn = locator.nth(idx)
            try:
                if not await btn.is_visible():
                    continue
                text = re.sub(r"\s+", " ", (await btn.inner_text()).strip())
                if not self._looks_like_order_action(text):
                    continue
                if not await self._is_disabled_button(btn):
                    continue
                card_text = await self._extract_card_text(btn)
                if not card_text:
                    continue
                for raw_line in card_text.splitlines():
                    candidate = self._clean_product_name(raw_line)
                    if candidate and candidate not in results:
                        results.append(candidate)
                        break
            except Exception as exc:
                logger.info("Stoplist disabled button inspect failed index=%s error=%s", idx, exc)
        return results

    async def collect_stoplist(self, point_name: str) -> dict:
        point = resolve_italian_pizza_point(point_name)
        if not point:
            return {
                "status": "failed",
                "point_name": point_name,
                "report_text": f"Не удалось определить публичную точку для стоп-листа: {point_name}",
            }
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
                await page.wait_for_timeout(2000)
                await self._dismiss_common_overlays(page)
                issue = self._detect_public_page_issue(await page.locator("body").inner_text())
                if issue:
                    return self._build_failed_result(point.display_name, issue)
                await self._open_address_modal(page, point)
                await self._set_delivery_mode(page)
                await self._fill_address(page, point)
                selected = await self._confirm_selected_point(page, point)
                logger.info("Stoplist point selected=%s point=%s", selected, point.display_name)
                await self._scroll_all(page)
                await self._dismiss_common_overlays(page)
                product_candidates = await self._collect_disabled_products(page)
                logger.info("Stoplist disabled button candidates point=%s items=%s", point.display_name, product_candidates[:60])
                cleaned: list[str] = []
                for item in product_candidates:
                    name = self._clean_product_name(item)
                    if name and name not in cleaned:
                        cleaned.append(name)
                if cleaned:
                    report_text = "Точка: {}\nСтоп-лист:\n{}".format(
                        point.display_name,
                        "\n".join(f"- {item}" for item in cleaned[:60]),
                    )
                else:
                    body = (await page.locator("body").inner_text())[:2000]
                    issue = self._detect_public_page_issue(body)
                    if issue:
                        return self._build_failed_result(point.display_name, issue)
                    report_text = (
                        f"Точка: {point.display_name}\n"
                        "Статус: не удалось выделить недоступные позиции детерминированно.\n"
                        f"Точка выбрана: {'да' if selected else 'нет'}\n\n"
                        f"Фрагмент страницы:\n{body}"
                    )
                return {
                    "status": "ok",
                    "point_name": point.display_name,
                    "selected": selected,
                    "report_text": report_text,
                    "alert_hash": None,
                }
            finally:
                await context.close()
                await browser.close()


italian_pizza_public_adapter = ItalianPizzaPublicAdapter()
