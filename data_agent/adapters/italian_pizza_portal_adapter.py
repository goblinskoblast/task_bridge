from __future__ import annotations

import hashlib
import logging
import re

from email_integration.encryption import decrypt_password

logger = logging.getLogger(__name__)


class ItalianPizzaPortalAdapter:
    def _period_candidates(self, lowered: str) -> list[str]:
        if "12 часов" in lowered:
            return ["12 часов", "12ч", "За 12 часов", "Последние 12 часов", "12"]
        if "3 часа" in lowered:
            return ["3 часа", "3ч", "За 3 часа", "Последние 3 часа", "3"]
        if "сутки" in lowered or "24 часа" in lowered:
            return ["Сутки", "24 часа", "За сутки", "Последние сутки", "24"]
        if "сегодня" in lowered:
            return ["Сегодня"]
        return []

    async def _visible_period_controls(self, page) -> list[str]:
        js = """
        () => {
          const isVisible = (el) => {
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style && style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
          };
          const texts = [];
          for (const el of document.querySelectorAll('button, [role="button"], [role="tab"], label, span, div, li, option')) {
            if (!isVisible(el)) continue;
            const text = String(el.innerText || el.textContent || '').split('\n').map((s) => s.trim()).filter(Boolean).join(' ');
            if (!text || text.length > 80) continue;
            const lower = text.toLowerCase();
            if (!(lower.includes('час') || lower.includes('сут') || lower.includes('сегод') || lower === '12' || lower === '3' || lower === '24' || lower === '15')) continue;
            texts.push(text);
          }
          return Array.from(new Set(texts)).slice(0, 40);
        }
        """
        try:
            return await page.evaluate(js)
        except Exception as exc:
            logger.info("Blanks period control collect failed error=%s", exc)
            return []

    async def _click_best_period_candidate(self, page, candidates: list[str]) -> bool:
        lowered_candidates = [candidate.lower() for candidate in candidates if candidate]
        js = """
        (wanted) => {
          const isVisible = (el) => {
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style && style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
          };
          let best = null;
          for (const el of document.querySelectorAll('button, [role="button"], [role="tab"], label, span, div, li, option')) {
            if (!isVisible(el)) continue;
            const text = String(el.innerText || el.textContent || '').split('\n').map((s) => s.trim()).filter(Boolean).join(' ');
            if (!text || text.length > 80) continue;
            const lower = text.toLowerCase();
            let score = 0;
            for (const candidate of wanted) {
              if (!candidate) continue;
              if (lower === candidate) score += 10;
              else if (lower.includes(candidate)) score += 4;
            }
            if (lower.includes('час')) score += 1;
            if (score < 5) continue;
            if (!best || score > best.score) best = { score, text, el };
          }
          if (!best) return { clicked: false, text: '' };
          best.el.click();
          return { clicked: true, text: best.text, score: best.score };
        }
        """
        try:
            result = await page.evaluate(js, lowered_candidates)
            logger.info("Blanks period click result=%s", result)
            return bool(result and result.get("clicked"))
        except Exception as exc:
            logger.info("Blanks period click failed error=%s", exc)
            return False

    async def _open_period_menu_if_needed(self, page) -> None:
        openers = ["15 часов", "12 часов", "3 часа", "Сутки", "Период", "За период"]
        for candidate in openers:
            locator = page.locator(f"text={candidate}")
            if await locator.count() > 0:
                try:
                    await locator.first.click(timeout=2000)
                    await page.wait_for_timeout(900)
                    logger.info("Blanks period opener clicked=%s", candidate)
                    return
                except Exception:
                    continue

    async def _select_period(self, page, period_hint: str) -> None:
        if not period_hint:
            return
        lowered = period_hint.lower()
        candidates = self._period_candidates(lowered)
        if not candidates:
            return
        for candidate in candidates:
            locator = page.locator(f"text={candidate}")
            if await locator.count() > 0:
                try:
                    await locator.first.click(timeout=3000)
                    await page.wait_for_timeout(1500)
                    logger.info("Blanks period selected candidate=%s", candidate)
                    return
                except Exception:
                    continue
        visible_controls = await self._visible_period_controls(page)
        logger.info("Blanks visible period controls=%s", visible_controls)
        await self._open_period_menu_if_needed(page)
        if await self._click_best_period_candidate(page, candidates):
            await page.wait_for_timeout(1500)
            return
        logger.info("Blanks period selector not found for period=%s candidates=%s", period_hint, candidates)

    def _normalize_report(self, point_name: str, data: str) -> tuple[str, bool]:
        raw = (data or "").strip()
        if not raw:
            return (f"Точка: {point_name}\nПроверка бланков не дала результата. Нужен повторный запуск.", False)
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

    async def collect_blanks(self, *, url: str, username: str, encrypted_password: str, point_name: str, period_hint: str) -> dict:
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
                for selector in ["input[name='username']", "input[name='login']", "input[type='email']"]:
                    if await page.locator(selector).count() > 0:
                        await page.fill(selector, username)
                        break
                for selector in ["input[type='password']", "input[name='password']"]:
                    if await page.locator(selector).count() > 0:
                        await page.fill(selector, password)
                        break
                for selector in ["button[type='submit']", "button:has-text('Войти')", "button:has-text('Login')"]:
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
                report_text, has_red_flags = self._normalize_report(point_name, body)
                alert_hash = hashlib.sha256(report_text.encode("utf-8", errors="ignore")).hexdigest()
                return {
                    "status": "ok",
                    "point_name": point_name,
                    "has_red_flags": has_red_flags,
                    "alert_hash": alert_hash,
                    "report_text": report_text,
                    "period_hint": period_hint or "текущий бланк",
                }
            finally:
                await context.close()
                await browser.close()


italian_pizza_portal_adapter = ItalianPizzaPortalAdapter()
