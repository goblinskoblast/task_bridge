from __future__ import annotations

import hashlib
import logging
import re

from email_integration.encryption import decrypt_password

logger = logging.getLogger(__name__)


class ItalianPizzaPortalAdapter:
    def _build_diagnostics(self, stage: str, url: str, **extra) -> dict:
        diagnostics = {"stage": stage, "url": url}
        for key, value in extra.items():
            if value is None:
                continue
            diagnostics[key] = value
        return diagnostics

    def _normalize_text(self, text: str) -> str:
        normalized = re.sub(r"\s+", " ", (text or "").strip().lower())
        return normalized.replace("ё", "е")

    def _point_variants(self, point_name: str) -> list[str]:
        variants: list[str] = []
        city = point_name.split(",")[0].strip()
        address = point_name.split(",")[-1].strip()
        seeds = [
            point_name,
            city,
            address,
            f"{city} {address}",
            city.split()[-1] if city else "",
        ]
        for raw in seeds:
            normalized = re.sub(r"\s+", " ", (raw or "").strip())
            if normalized and normalized not in variants:
                variants.append(normalized)
        return variants

    def _point_tokens(self, point_name: str) -> list[str]:
        tokens: list[str] = []
        for variant in self._point_variants(point_name):
            for token in re.split(r"[\s,./-]+", variant.lower()):
                token = token.strip()
                if len(token) < 2:
                    continue
                if token not in tokens:
                    tokens.append(token)
        return tokens

    def _point_appears_selected(self, text: str, point_name: str) -> bool:
        lowered = re.sub(r"\s+", " ", (text or "").lower()).strip()
        return any(
            candidate.lower() in lowered
            for candidate in self._point_variants(point_name)
            if len(candidate) >= 3
        )

    def _point_match_score(self, text: str, point_name: str) -> int:
        lowered = self._normalize_text(text)
        score = 0
        for candidate in self._point_variants(point_name):
            normalized_candidate = self._normalize_text(candidate)
            if not normalized_candidate:
                continue
            if lowered == normalized_candidate:
                score += 12
            elif normalized_candidate in lowered:
                score += 6
        for token in self._point_tokens(point_name):
            if token in lowered:
                score += 2 if not any(ch.isdigit() for ch in token) else 4
        return score

    async def _iter_point_controls(self, page, point_name: str, max_items: int = 220) -> list[tuple[int, str, int]]:
        locator = page.locator("button, [role='button'], [role='option'], [role='tab'], label, span, div, li, option")
        count = min(await locator.count(), max_items)
        results: list[tuple[int, str, int]] = []
        for idx in range(count):
            item = locator.nth(idx)
            try:
                if not await item.is_visible():
                    continue
                text = (await item.inner_text()).strip()
            except Exception:
                continue
            if not text or len(text) > 120:
                continue
            normalized = re.sub(r"\s+", " ", text)
            lowered = self._normalize_text(normalized)
            if any(marker in lowered for marker in ["логин", "пароль", "войти", "выход", "поддержка"]):
                continue
            score = self._point_match_score(normalized, point_name)
            results.append((idx, normalized, score))
        return results

    async def _visible_point_controls(self, page, point_name: str) -> list[str]:
        controls = await self._iter_point_controls(page, point_name)
        seen: list[str] = []
        for _, text, score in sorted(controls, key=lambda item: item[2], reverse=True):
            if text in seen:
                continue
            if score > 0 or len(seen) < 12:
                seen.append(text)
        return seen[:20]

    async def _open_point_menu_if_needed(self, page) -> None:
        openers = ["Точка", "Выберите точку", "Ресторан", "Подразделение", "Филиал", "Сменить точку"]
        for candidate in openers:
            locator = page.locator(f"text={candidate}")
            if await locator.count() == 0:
                continue
            try:
                await locator.first.click(timeout=2500)
                await page.wait_for_timeout(900)
                logger.info("Blanks point opener clicked=%s", candidate)
                return
            except Exception:
                continue

    async def _click_best_point_candidate(self, page, point_name: str) -> tuple[str | None, list[str]]:
        controls = await self._iter_point_controls(page, point_name)
        visible_controls = []
        best_idx = None
        best_text = None
        best_score = 0
        for idx, text, score in controls:
            if text not in visible_controls:
                visible_controls.append(text)
            if score > best_score:
                best_idx = idx
                best_text = text
                best_score = score
        logger.info(
            "Blanks point candidates best_text=%s best_score=%s visible_controls=%s",
            best_text,
            best_score,
            visible_controls[:12],
        )
        if best_idx is None or best_score < 6:
            return None, visible_controls[:12]
        locator = page.locator("button, [role='button'], [role='option'], [role='tab'], label, span, div, li, option")
        try:
            await locator.nth(best_idx).click(timeout=2500)
            await page.wait_for_timeout(900)
            return best_text, visible_controls[:12]
        except Exception as exc:
            logger.info("Blanks point candidate click failed idx=%s text=%s error=%s", best_idx, best_text, exc)
            return None, visible_controls[:12]

    async def _select_point(self, page, point_name: str) -> dict:
        matched_point = None
        for candidate in self._point_variants(point_name):
            locator = page.locator(f"text={candidate}")
            if await locator.count() == 0:
                continue
            try:
                await locator.first.click(timeout=3000)
                await page.wait_for_timeout(900)
                matched_point = candidate
                break
            except Exception:
                continue
        visible_point_controls: list[str] = []
        if matched_point is None:
            visible_point_controls = await self._visible_point_controls(page, point_name)
            await self._open_point_menu_if_needed(page)
            matched_point, visible_point_controls = await self._click_best_point_candidate(page, point_name)
        return {
            "selected": matched_point is not None,
            "matched_point": matched_point,
            "point_candidates": self._point_variants(point_name),
            "visible_point_controls": visible_point_controls,
        }

    def _detect_terminal_issue(self, text: str) -> str | None:
        lowered = re.sub(r"\s+", " ", (text or "").lower()).strip()
        if not lowered:
            return None
        if any(token in lowered for token in ["код подтверждения", "sms", "2fa", "двухфактор"]):
            return "Требуется 2FA или код подтверждения."
        if any(token in lowered for token in ["неверный пароль", "неверный логин", "invalid credentials", "wrong password", "логин или пароль"]):
            return "Не удалось войти в портал: проверьте логин и пароль."
        if any(token in lowered for token in ["нет доступа", "access denied", "403", "forbidden", "permission denied"]):
            return "Портал вернул отказ в доступе."
        return None

    def _looks_like_login_page(self, text: str) -> bool:
        lowered = self._normalize_text(text)
        login_markers = ["логин", "пароль", "войти", "login", "password", "remember me"]
        return sum(1 for marker in login_markers if marker in lowered) >= 2

    def _contains_report_context(self, text: str) -> bool:
        lowered = self._normalize_text(text)
        report_markers = ["бланк", "перегруз", "отклон", "лимит", "норматив", "красн", "отчет", "отчёт"]
        return any(marker in lowered for marker in report_markers)

    def _build_failed_result(
        self,
        point_name: str,
        issue_text: str,
        period_hint: str,
        diagnostics: dict | None = None,
    ) -> dict:
        report_text = f"Точка: {point_name}\nСтатус: {issue_text}"
        return {
            "status": "failed",
            "point_name": point_name,
            "has_red_flags": False,
            "alert_hash": None,
            "report_text": report_text,
            "period_hint": period_hint or "текущий бланк",
            "message": issue_text,
            "diagnostics": diagnostics or {},
        }

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

    async def _iter_period_controls(self, page, max_items: int = 200) -> list[tuple[int, str]]:
        locator = page.locator("button, [role='button'], [role='tab'], label, span, div, li, option")
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
            if not text or len(text) > 80:
                continue
            normalized = re.sub(r"\s+", " ", text)
            lowered = normalized.lower()
            if not ("час" in lowered or "сут" in lowered or "сегод" in lowered or lowered in {"12", "3", "24", "15"}):
                continue
            results.append((idx, normalized))
        return results

    async def _visible_period_controls(self, page) -> list[str]:
        controls = await self._iter_period_controls(page)
        seen: list[str] = []
        for _, text in controls:
            if text not in seen:
                seen.append(text)
        return seen[:40]

    async def _click_best_period_candidate(self, page, candidates: list[str]) -> bool:
        wanted = [candidate.lower() for candidate in candidates if candidate]
        locator = page.locator("button, [role='button'], [role='tab'], label, span, div, li, option")
        controls = await self._iter_period_controls(page)
        best_idx = None
        best_text = ""
        best_score = 0
        for idx, text in controls:
            lowered = text.lower()
            score = 0
            for candidate in wanted:
                if lowered == candidate:
                    score += 10
                elif candidate in lowered:
                    score += 4
            if "час" in lowered:
                score += 1
            if score > best_score:
                best_idx = idx
                best_text = text
                best_score = score
        if best_idx is None or best_score < 5:
            logger.info("Blanks period click result=%s", {"clicked": False, "text": best_text, "score": best_score})
            return False
        try:
            await locator.nth(best_idx).click(timeout=2500)
            logger.info("Blanks period click result=%s", {"clicked": True, "text": best_text, "score": best_score})
            return True
        except Exception as exc:
            logger.info("Blanks period click failed idx=%s text=%s error=%s", best_idx, best_text, exc)
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

    async def _select_period(self, page, period_hint: str) -> dict:
        if not period_hint:
            return {"selected": True, "matched_period": None, "visible_period_controls": []}
        lowered = period_hint.lower()
        candidates = self._period_candidates(lowered)
        if not candidates:
            return {"selected": False, "matched_period": None, "visible_period_controls": []}
        for candidate in candidates:
            locator = page.locator(f"text={candidate}")
            if await locator.count() > 0:
                try:
                    await locator.first.click(timeout=3000)
                    await page.wait_for_timeout(900)
                    logger.info("Blanks period selected candidate=%s", candidate)
                    return {"selected": True, "matched_period": candidate, "visible_period_controls": []}
                except Exception:
                    continue
        visible_controls = await self._visible_period_controls(page)
        logger.info("Blanks visible period controls=%s", visible_controls)
        await self._open_period_menu_if_needed(page)
        if await self._click_best_period_candidate(page, candidates):
            await page.wait_for_timeout(900)
            return {
                "selected": True,
                "matched_period": candidates[0],
                "visible_period_controls": visible_controls[:10],
            }
        logger.info("Blanks period selector not found for period=%s candidates=%s", period_hint, candidates)
        return {
            "selected": False,
            "matched_period": None,
            "visible_period_controls": visible_controls[:10],
        }

    def _normalize_report(self, point_name: str, data: str) -> tuple[str, bool]:
        raw = (data or "").strip()
        if not raw:
            return (f"Точка: {point_name}\nПроверка бланков не дала результата. Нужен повторный запуск.", False)
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        filtered: list[str] = []
        for line in lines:
            lowered = line.lower()
            if any(
                marker in lowered
                for marker in [
                    "cookie",
                    "войти",
                    "login",
                    "пароль",
                    "логин",
                    "скачать приложение",
                    "главная",
                    "настройки",
                    "поддержка",
                    "профиль",
                    "выйти",
                    "выберите точку",
                ]
            ):
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
        stage = "launch"
        current_url = url
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context(locale="ru-RU", timezone_id="Europe/Moscow")
            page = await context.new_page()
            try:
                stage = "goto"
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                current_url = page.url
                await page.wait_for_timeout(700)
                stage = "login_username"
                for selector in ["input[name='username']", "input[name='login']", "input[type='email']"]:
                    if await page.locator(selector).count() > 0:
                        await page.fill(selector, username)
                        break
                stage = "login_password"
                for selector in ["input[type='password']", "input[name='password']"]:
                    if await page.locator(selector).count() > 0:
                        await page.fill(selector, password)
                        break
                stage = "login_submit"
                for selector in ["button[type='submit']", "button:has-text('Войти')", "button:has-text('Login')"]:
                    if await page.locator(selector).count() > 0:
                        await page.locator(selector).first.click()
                        break
                await page.wait_for_timeout(900)
                current_url = page.url
                post_login_text = await page.locator("body").inner_text()
                issue = self._detect_terminal_issue(post_login_text)
                if issue:
                    return self._build_failed_result(
                        point_name,
                        issue,
                        period_hint,
                        diagnostics=self._build_diagnostics(stage, current_url),
                    )
                if self._looks_like_login_page(post_login_text):
                    return self._build_failed_result(
                        point_name,
                        "Не удалось войти в портал: форма авторизации осталась открыта.",
                        period_hint,
                        diagnostics=self._build_diagnostics(stage, current_url),
                    )
                stage = "point_selection"
                point_result = await self._select_point(page, point_name)
                current_url = page.url
                point_selected = point_result["selected"]
                if not point_selected:
                    body_text = await page.locator("body").inner_text()
                    point_selected = self._point_appears_selected(body_text, point_name)
                if not point_selected:
                    return self._build_failed_result(
                        point_name,
                        "Не удалось выбрать нужную точку на портале.",
                        period_hint,
                        diagnostics=self._build_diagnostics(
                            stage,
                            current_url,
                            point_selected=False,
                            matched_point=point_result["matched_point"],
                            point_candidates=point_result["point_candidates"],
                            visible_point_controls=point_result["visible_point_controls"],
                            page_excerpt=self._normalize_text(body_text)[:400],
                        ),
                    )
                stage = "report_navigation"
                for candidate in ["Отчеты", "Отчёты", "Отчет по перегрузкам", "Отчёт по перегрузкам", "Перегрузки", "Бланк загрузки"]:
                    locator = page.locator(f"text={candidate}")
                    if await locator.count() > 0:
                        try:
                            await locator.first.click(timeout=3000)
                            await page.wait_for_timeout(900)
                            current_url = page.url
                        except Exception:
                            continue
                stage = "period_selection"
                period_result = await self._select_period(page, period_hint)
                if period_hint and not period_result["selected"]:
                    return self._build_failed_result(
                        point_name,
                        "Не удалось выбрать нужный период на портале.",
                        period_hint,
                        diagnostics=self._build_diagnostics(
                            stage,
                            page.url,
                            point_selected=point_selected,
                            matched_point=point_result["matched_point"],
                            visible_point_controls=point_result["visible_point_controls"],
                            period_selected=False,
                            matched_period=period_result["matched_period"],
                            visible_period_controls=period_result["visible_period_controls"],
                        ),
                    )
                stage = "report_read"
                body = (await page.locator("body").inner_text())[:8000]
                issue = self._detect_terminal_issue(body)
                if issue:
                    return self._build_failed_result(
                        point_name,
                        issue,
                        period_hint,
                        diagnostics=self._build_diagnostics(
                            stage,
                            page.url,
                            point_selected=point_selected,
                            matched_point=point_result["matched_point"],
                            visible_point_controls=point_result["visible_point_controls"],
                            period_selected=period_result["selected"],
                            matched_period=period_result["matched_period"],
                            visible_period_controls=period_result["visible_period_controls"],
                        ),
                    )
                if self._looks_like_login_page(body):
                    return self._build_failed_result(
                        point_name,
                        "Не удалось открыть отчет по бланкам: портал вернул на страницу входа.",
                        period_hint,
                        diagnostics=self._build_diagnostics(
                            stage,
                            page.url,
                            point_selected=point_selected,
                            matched_point=point_result["matched_point"],
                            visible_point_controls=point_result["visible_point_controls"],
                            period_selected=period_result["selected"],
                            matched_period=period_result["matched_period"],
                            visible_period_controls=period_result["visible_period_controls"],
                        ),
                    )
                if not self._contains_report_context(body):
                    return self._build_failed_result(
                        point_name,
                        "Не удалось подтвердить открытие отчета по бланкам на портале.",
                        period_hint,
                        diagnostics=self._build_diagnostics(
                            stage,
                            page.url,
                            point_selected=point_selected,
                            matched_point=point_result["matched_point"],
                            visible_point_controls=point_result["visible_point_controls"],
                            period_selected=period_result["selected"],
                            matched_period=period_result["matched_period"],
                            visible_period_controls=period_result["visible_period_controls"],
                        ),
                    )
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
                    "diagnostics": self._build_diagnostics(
                        stage,
                        page.url,
                        point_selected=point_selected,
                        matched_point=point_result["matched_point"],
                        visible_point_controls=point_result["visible_point_controls"],
                        period_selected=period_result["selected"],
                        matched_period=period_result["matched_period"],
                        visible_period_controls=period_result["visible_period_controls"],
                    ),
                }
            except Exception as exc:
                logger.error(
                    "Blanks adapter failed point=%s stage=%s url=%s error=%s",
                    point_name,
                    stage,
                    current_url,
                    exc,
                    exc_info=True,
                )
                return self._build_failed_result(
                    point_name,
                    f"Техническая ошибка при проверке бланков: {exc}",
                    period_hint,
                    diagnostics=self._build_diagnostics(stage, current_url),
                )
            finally:
                await context.close()
                await browser.close()


italian_pizza_portal_adapter = ItalianPizzaPortalAdapter()
