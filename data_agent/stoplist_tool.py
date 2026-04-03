from __future__ import annotations

import logging
import re

from .italian_pizza import resolve_italian_pizza_point

logger = logging.getLogger(__name__)

_CATEGORY_STOPWORDS = {
    "пицца", "комбо", "детское меню", "десерты", "напитки", "закуски", "салаты", "соусы",
    "роллы", "бургеры", "паста", "горячее", "супы", "войти", "контакты", "доставка",
    "заказать доставку", "выберите адрес", "меню", "фильтры", "еще",
}


class StoplistTool:
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

    async def _click_text_candidate(self, page, candidate: str) -> bool:
        if not candidate:
            return False
        try:
            locator = page.get_by_text(re.compile(re.escape(candidate), re.IGNORECASE))
            if await locator.count() > 0:
                await locator.first.click(timeout=3000)
                await page.wait_for_timeout(1800)
                logger.info("Stoplist selected point via text candidate=%s", candidate)
                return True
        except Exception:
            pass
        return False

    async def _log_address_candidates(self, page, city: str) -> None:
        try:
            candidates = await page.evaluate(
                """
                (city) => {
                  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
                  const hasDigit = (s) => Array.from(s).some(ch => ch >= '0' && ch <= '9');
                  const elements = Array.from(document.querySelectorAll('button, a, div, span, li'));
                  const out = [];
                  for (const el of elements) {
                    const text = norm(el.innerText || '');
                    if (!text || text.length > 180) continue;
                    const lowered = text.toLowerCase();
                    if (lowered.includes(city.toLowerCase()) || hasDigit(text) || lowered.includes('адрес')) out.push(text);
                  }
                  return [...new Set(out)].slice(0, 30);
                }
                """,
                city,
            )
            logger.info("Stoplist address candidates=%s", candidates)
        except Exception as exc:
            logger.info("Stoplist address candidate log failed error=%s", exc)

    async def _click_best_match_via_js(self, page, candidates: list[str]) -> bool:
        try:
            clicked = await page.evaluate(
                """
                (candidates) => {
                  const norm = (s) => (s || '').toLowerCase().replace(/\\s+/g, ' ').trim();
                  const elements = Array.from(document.querySelectorAll('button, a, div, span, li'));
                  let best = null;
                  let bestScore = 0;
                  for (const el of elements) {
                    const text = norm(el.innerText);
                    if (!text || text.length > 300) continue;
                    for (const candidate of candidates) {
                      const c = norm(candidate);
                      if (!c) continue;
                      let score = 0;
                      if (text === c) score += 10;
                      if (text.includes(c)) score += 5;
                      for (const token of c.replace(/[,/.]/g, ' ').split(' ')) {
                        if (token.length >= 2 && text.includes(token)) score += 2;
                      }
                      if (score > bestScore) {
                        bestScore = score;
                        best = el;
                      }
                    }
                  }
                  if (best && bestScore >= 8) {
                    best.click();
                    return {clicked: true, score: bestScore, text: best.innerText};
                  }
                  return {clicked: false, score: bestScore, text: best ? best.innerText : ''};
                }
                """,
                candidates,
            )
            logger.info("Stoplist JS point match result=%s", clicked)
            if clicked and clicked.get("clicked"):
                await page.wait_for_timeout(1800)
                return True
        except Exception as exc:
            logger.info("Stoplist JS point match failed error=%s", exc)
        return False

    async def _fill_address_and_select(self, page, point) -> bool:
        address_query = point.address.split(",")[-1].strip() or point.address
        input_selectors = [
            "input[placeholder*='Введите адрес']",
            "input[placeholder*='адрес']",
            "input[type='text']",
        ]
        for selector in input_selectors:
            try:
                locator = page.locator(selector)
                if await locator.count() == 0:
                    continue
                await locator.first.click()
                await locator.first.fill("")
                await locator.first.fill(address_query)
                await locator.first.dispatch_event("input")
                await locator.first.dispatch_event("change")
                await page.wait_for_timeout(1800)
                logger.info("Stoplist filled address input selector=%s value=%s", selector, address_query)

                suggestion_candidates = [
                    f"{point.city}, {point.address}",
                    point.address,
                    point.address.replace(",", ""),
                    point.address.split(",")[-1].strip(),
                ]
                for candidate in suggestion_candidates:
                    if await self._click_text_candidate(page, candidate):
                        return True
                if await self._click_best_match_via_js(page, suggestion_candidates):
                    return True

                await locator.first.press("Enter")
                await page.wait_for_timeout(1800)
                logger.info("Stoplist pressed Enter after address input selector=%s", selector)
                for candidate in suggestion_candidates:
                    if await self._click_text_candidate(page, candidate):
                        return True
            except Exception as exc:
                logger.info("Stoplist address input flow failed selector=%s error=%s", selector, exc)
        return False

    async def _scroll_all(self, page) -> None:
        for _ in range(10):
            try:
                await page.mouse.wheel(0, 1800)
            except Exception:
                await page.evaluate("window.scrollBy(0, 1800)")
            await page.wait_for_timeout(700)

    async def _select_public_point(self, page, point) -> bool:
        for candidate in ["Выберите адрес", point.city]:
            locator = page.locator(f"text={candidate}")
            if await locator.count() > 0:
                try:
                    await locator.first.click(timeout=3000)
                    await page.wait_for_timeout(1500)
                    logger.info("Stoplist opened address selector via=%s", candidate)
                    break
                except Exception:
                    continue

        body_after_open = (await page.locator("body").inner_text())[:1500]
        logger.info("Stoplist body after selector open preview=%s", body_after_open.replace("\n", " | "))
        await self._log_address_candidates(page, point.city)

        if await self._fill_address_and_select(page, point):
            return True

        address_candidates = [
            point.display_name,
            point.address,
            point.address.replace(",", ""),
            point.address.split(",")[-1].strip(),
            f"{point.city} {point.address}",
        ]
        for candidate in address_candidates:
            if await self._click_text_candidate(page, candidate):
                return True
        if await self._click_best_match_via_js(page, address_candidates):
            return True

        logger.info("Stoplist point selector not confirmed for=%s", point.display_name)
        return False

    async def _collect_disabled_products(self, page) -> list[str]:
        try:
            items = await page.evaluate(
                """
                () => {
                  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
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
                    const lines = text.split(/\n+/).map(norm).filter(Boolean);
                    const product = lines.find(line => {
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
                target_url = point.public_url.rstrip("/") + "/"
                logger.info("Stoplist public browser run point=%s url=%s", point.display_name, target_url)
                await page.goto(target_url, wait_until="domcontentloaded", timeout=25000)
                await page.wait_for_timeout(2500)

                selected = await self._select_public_point(page, point)
                logger.info("Stoplist point selected=%s point=%s", selected, point.display_name)

                await self._scroll_all(page)

                product_candidates = await self._collect_disabled_products(page)
                logger.info("Stoplist disabled button candidates point=%s items=%s", point.display_name, product_candidates[:60])
                if product_candidates:
                    cleaned = []
                    for item in product_candidates:
                        name = self._clean_product_name(item)
                        if name and name not in cleaned:
                            cleaned.append(name)
                    if cleaned:
                        return f"Точка: {point.display_name}\nСтоп-лист:\n" + "\n".join(f"- {item}" for item in cleaned[:60])

                body = (await page.locator("body").inner_text())[:5000]
                preview = body[:2000]
                return (
                    f"Точка: {point.display_name}\n"
                    "Статус: не удалось выделить недоступные позиции детерминированно.\n"
                    f"Точка выбрана: {'да' if selected else 'нет'}\n\n"
                    f"Фрагмент страницы:\n{preview}"
                )
            finally:
                await context.close()
                await browser.close()

    async def collect_for_point(self, *, url: str, username: str, encrypted_password: str, point_name: str) -> dict:
        report_text = await self._collect_public_stoplist(point_name)
        return {"status": "ok", "point_name": point_name, "report_text": report_text}


stoplist_tool = StoplistTool()
