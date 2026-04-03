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

    async def _collect_suggestion_candidates(self, page, query: str) -> list[str]:
        street = query.split()[0].lower()
        number_tokens = [token for token in query.split() if any(ch.isdigit() for ch in token)]
        js = """
        (params) => {
          const street = String(params.street || '').toLowerCase();
          const numbers = Array.isArray(params.numbers) ? params.numbers.map(String) : [];
          const isVisible = (el) => {
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style && style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
          };
          const texts = [];
          for (const el of document.querySelectorAll('button, [role="option"], [role="button"], li, div, span')) {
            if (!isVisible(el)) continue;
            const text = String(el.innerText || '').split('\n').map((s) => s.trim()).filter(Boolean).join(' ');
            if (!text || text.length > 140) continue;
            const lower = text.toLowerCase();
            if (street && !lower.includes(street) && !numbers.some((token) => lower.includes(token))) continue;
            if (lower.includes('выберите адрес') || lower === 'доставка' || lower === 'самовывоз') continue;
            texts.push(text);
          }
          return Array.from(new Set(texts)).slice(0, 30);
        }
        """
        try:
            return await page.evaluate(js, {"street": street, "numbers": number_tokens})
        except Exception as exc:
            logger.info("Stoplist suggestion candidate collect failed error=%s", exc)
            return []

    async def _click_suggestion(self, page, query: str) -> bool:
        street = query.split()[0].lower()
        tail = query.lower()
        number_tokens = [token for token in query.split() if any(ch.isdigit() for ch in token)]
        js = """
        (params) => {
          const street = String(params.street || '').toLowerCase();
          const tail = String(params.tail || '').toLowerCase();
          const numbers = Array.isArray(params.numbers) ? params.numbers.map(String) : [];
          const isVisible = (el) => {
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style && style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
          };
          let best = null;
          for (const el of document.querySelectorAll('button, [role="option"], [role="button"], li, div, span')) {
            if (!isVisible(el)) continue;
            const text = String(el.innerText || '').split('\n').map((s) => s.trim()).filter(Boolean).join(' ');
            if (!text || text.length > 140) continue;
            const lower = text.toLowerCase();
            if (lower.includes('выберите адрес') || lower === 'доставка' || lower === 'самовывоз') continue;
            let score = 0;
            if (tail && lower.includes(tail)) score += 10;
            if (street && lower.includes(street)) score += 4;
            for (const token of numbers) {
              if (token && lower.includes(token)) score += 6;
            }
            if (score < 8) continue;
            if (!best || score > best.score) best = { score, text, el };
          }
          if (!best) return { clicked: false, score: 0, text: '' };
          best.el.click();
          return { clicked: true, score: best.score, text: best.text };
        }
        """
        try:
            result = await page.evaluate(js, {"street": street, "tail": tail, "numbers": number_tokens})
            logger.info("Stoplist suggestion click result=%s", result)
            return bool(result and result.get("clicked"))
        except Exception as exc:
            logger.info("Stoplist suggestion click failed error=%s", exc)
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
                except Exception:
                    continue
                try:
                    await field.click()
                    await field.fill("")
                    await field.fill(query)
                    await field.dispatch_event("input")
                    await field.dispatch_event("change")
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

    async def _collect_disabled_products(self, page) -> list[str]:
        results: list[str] = []
        try:
            buttons = page.get_by_text("Выбрать", exact=True)
            count = await buttons.count()
            for idx in range(count):
                btn = buttons.nth(idx)
                try:
                    if not await btn.is_visible():
                        continue
                    card_info = await btn.evaluate(
                        """
                        (node) => {
                          const style = window.getComputedStyle(node);
                          const cls = String(node.className || '').toLowerCase();
                          const disabled = node.hasAttribute('disabled')
                            || node.getAttribute('aria-disabled') === 'true'
                            || style.pointerEvents === 'none'
                            || Number.parseFloat(style.opacity || '1') < 0.7
                            || cls.includes('disabled')
                            || cls.includes('unavailable')
                            || cls.includes('gray')
                            || String(style.filter || '').includes('grayscale');
                          if (!disabled) return null;
                          const card = node.closest('article, li, [class*=item], [class*=card], [class*=product], div');
                          if (!card) return null;
                          return {
                            buttonClass: cls,
                            text: String(card.innerText || '').split('\n').map((s) => s.trim()).filter(Boolean).join('\n')
                          };
                        }
                        """
                    )
                    if not card_info:
                        continue
                    card_text = str(card_info.get("text") or "")
                    for raw_line in card_text.splitlines():
                        candidate = self._clean_product_name(raw_line)
                        if candidate and candidate not in results:
                            results.append(candidate)
                            break
                except Exception as exc:
                    logger.info("Stoplist disabled button inspect failed index=%s error=%s", idx, exc)
        except Exception as exc:
            logger.info("Stoplist disabled-product collect failed error=%s", exc)
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
                await self._open_address_modal(page, point)
                await self._set_delivery_mode(page)
                await self._fill_address(page, point)
                selected = await self._confirm_selected_point(page, point)
                logger.info("Stoplist point selected=%s point=%s", selected, point.display_name)
                await self._scroll_all(page)
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
                }
            finally:
                await context.close()
                await browser.close()


italian_pizza_public_adapter = ItalianPizzaPublicAdapter()
