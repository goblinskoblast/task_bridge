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
                    await page.wait_for_timeout(1000)
                    logger.info("Stoplist filled address input selector=%s index=%s value=%s", selector, idx, query)
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
        page_text = (await page.locator("body").inner_text()).lower()
        tail = point.address.split(",")[-1].strip().lower()
        if tail and tail in page_text:
            logger.info("Stoplist inferred point selection by page text address=%s", point.address)
            return True
        for candidate in [point.address, point.display_name, tail]:
            if not candidate:
                continue
            try:
                locator = page.get_by_text(re.compile(re.escape(candidate), re.IGNORECASE))
                if await locator.count() > 0:
                    logger.info("Stoplist found address candidate in DOM=%s", candidate)
                    return True
            except Exception:
                continue
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
        try:
            items = await page.evaluate(
                """
                () => {
                  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
                  const looksLikePriceOrWeight = (s) => {
                    const lowered = s.toLowerCase();
                    const hasDigit = Array.from(lowered).some(ch => ch >= '0' && ch <= '9');
                    if (!hasDigit) return false;
                    return lowered.endsWith('₽') || lowered.endsWith('руб') || lowered.endsWith('г') || lowered.endsWith('кг');
                  };
                  const buttons = Array.from(document.querySelectorAll('button, a, div, span'));
                  const results = [];
                  const seen = new Set();
                  for (const btn of buttons) {
                    const btnText = norm(btn.innerText || '');
                    if (btnText !== 'Выбрать') continue;
                    const style = window.getComputedStyle(btn);
                    const cls = (btn.className || '').toString().toLowerCase();
                    const disabled = btn.hasAttribute('disabled')
                      || btn.getAttribute('aria-disabled') === 'true'
                      || style.pointerEvents === 'none'
                      || parseFloat(style.opacity || '1') < 0.7
                      || cls.includes('disabled')
                      || cls.includes('unavailable')
                      || cls.includes('gray')
                      || style.filter.includes('grayscale');
                    if (!disabled) continue;
                    const card = btn.closest('article, li, [class*="item"], [class*="card"], [class*="product"], div');
                    if (!card) continue;
                    const text = norm(card.innerText || '');
                    if (!text || text.length > 700) continue;
                    const lines = text.split('\n').map(norm).filter(Boolean);
                    const product = lines.find((line) => {
                      const lowered = line.toLowerCase();
                      if (['выбрать', 'фильтры', 'меню'].includes(lowered)) return false;
                      if (line.length < 3 || line.length > 120) return false;
                      if (looksLikePriceOrWeight(lowered)) return false;
                      return true;
                    });
                    if (!product) continue;
                    if (!seen.has(product)) {
                      seen.add(product);
                      results.push(product);
                    }
                  }
                  return results;
                }
                """
            )
            return items or []
        except Exception as exc:
            logger.info("Stoplist disabled-product collect failed error=%s", exc)
            return []

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
