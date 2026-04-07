from __future__ import annotations

import hashlib
import logging
import re

from email_integration.encryption import decrypt_password

logger = logging.getLogger(__name__)


class ItalianPizzaPortalAdapter:
    _POINT_CONTROL_SELECTOR = "button, [role='button'], [role='option'], [role='tab'], [role='menuitem'], label, span, div, li, option, a"
    _POINT_SEARCH_SELECTORS = [
        "input[placeholder*='точк']",
        "input[placeholder*='поиск']",
        "input[aria-label*='точк']",
        "input[type='search']",
        "[role='combobox'] input",
        "input[type='text']",
    ]

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
            f"{city}, {address}",
            f"{city} (1) {address}",
            f"{city} (1)",
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

    def _point_specificity_score(self, text: str, point_name: str) -> int:
        lowered = self._normalize_text(text)
        address = point_name.split(",")[-1].strip()
        address_tokens = [
            token
            for token in re.split(r"[\s,./-]+", self._normalize_text(address))
            if len(token) >= 2
        ]
        hits = 0
        for token in address_tokens:
            if token in lowered:
                hits += 1

        specificity = hits * 3
        if re.search(r"\(\d+\)", lowered):
            specificity += 2
        if len(lowered) >= 24:
            specificity += 1
        return specificity

    def _point_menu_looks_open(self, visible_controls: list[str]) -> bool:
        point_like_controls = [
            text
            for text in visible_controls
            if re.search(r"\(\d+\)", text or "")
        ]
        return len(point_like_controls) >= 2

    def _line_mentions_requested_point(self, text: str, point_name: str) -> bool:
        normalized = self._normalize_text(text)
        if not normalized:
            return False

        city = self._normalize_text(point_name.split(",")[0].strip())
        address = self._normalize_text(point_name.split(",")[-1].strip())
        if address and address in normalized:
            return True

        address_tokens = [
            token
            for token in re.split(r"[\s,./-]+", address)
            if len(token) >= 2
        ]
        normalized_tokens = {
            token
            for token in re.split(r"[\s,./-]+", normalized)
            if len(token) >= 2
        }
        token_hits = sum(1 for token in address_tokens if token in normalized_tokens)
        if token_hits >= min(2, len(address_tokens)):
            return True

        return bool(city and city in normalized and token_hits >= 1)

    def _body_mentions_requested_point(self, text: str, point_name: str) -> bool:
        lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
        return any(self._line_mentions_requested_point(line, point_name) for line in lines)

    def _extract_point_specific_body(self, text: str, point_name: str) -> tuple[str, bool]:
        lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
        if not lines:
            return "", False

        report_markers = ("бланк", "перегруз", "отклон", "лимит", "норматив", "красн", "отчет", "отчёт")
        kept_lines: list[str] = []
        matched_rows = False
        for line in lines:
            if self._line_mentions_requested_point(line, point_name):
                kept_lines.append(line)
                matched_rows = True
                continue
            lowered = self._normalize_text(line)
            if any(marker in lowered for marker in report_markers):
                kept_lines.append(line)
        return "\n".join(kept_lines), matched_rows

    def _is_point_menu_control(self, text: str) -> bool:
        lowered = self._normalize_text(text)
        return any(marker in lowered for marker in ["выбрать точку продаж", "точка продаж", "выберите точку"])

    def _label_match_score(self, text: str, labels: list[str]) -> int:
        lowered = self._normalize_text(text)
        best_score = 0
        for raw_label in labels:
            label = self._normalize_text(raw_label)
            if not label:
                continue
            if lowered == label:
                best_score = max(best_score, 120)
                continue
            if lowered.startswith(f"{label} "):
                best_score = max(best_score, 95)
            if label in lowered:
                best_score = max(best_score, 70)
            token_hits = 0
            for token in re.split(r"[\s,./-]+", label):
                token = token.strip()
                if len(token) < 2:
                    continue
                if token in lowered:
                    token_hits += 1
            if token_hits:
                best_score = max(best_score, 20 + token_hits * 12)
        return best_score

    async def _iter_controls_for_labels(self, page, labels: list[str], max_items: int = 220) -> list[tuple[int, str, int]]:
        locator = page.locator(self._POINT_CONTROL_SELECTOR)
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
            if not text or len(text) > 160:
                continue
            normalized = re.sub(r"\s+", " ", text)
            score = self._label_match_score(normalized, labels)
            if score <= 0:
                continue
            results.append((idx, normalized, score))
        return results

    async def _dispatch_visible_text_candidate_click(self, page, labels: list[str]) -> str | None:
        cleaned_labels = []
        for raw in labels:
            normalized = re.sub(r"\s+", " ", (raw or "").strip())
            if normalized and normalized not in cleaned_labels:
                cleaned_labels.append(normalized)
        if not cleaned_labels:
            return None

        result = await page.evaluate(
            """
            (labels) => {
              const normalize = (value) => (value || "").toLowerCase().replace(/ё/g, "е").replace(/\\s+/g, " ").trim();
              const labelTokens = labels
                .map((label) => normalize(label))
                .filter(Boolean)
                .map((label) => ({ label, tokens: label.split(/[\\s,./-]+/).filter((item) => item.length >= 2) }));
              const isVisible = (node) => {
                if (!(node instanceof Element)) return false;
                const style = window.getComputedStyle(node);
                if (!style || style.display === "none" || style.visibility === "hidden" || style.opacity === "0") {
                  return false;
                }
                const rect = node.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
              };
              let best = null;
              for (const node of Array.from(document.querySelectorAll("button, [role='button'], [role='option'], [role='tab'], [role='menuitem'], label, span, div, li, option, a"))) {
                if (!isVisible(node)) continue;
                const rawText = (node.innerText || node.textContent || "").replace(/\\s+/g, " ").trim();
                const text = normalize(rawText);
                if (!text || text.length > 160) continue;
                let score = 0;
                for (const item of labelTokens) {
                  if (text === item.label) {
                    score = Math.max(score, 120);
                    continue;
                  }
                  if (text.startsWith(item.label + " ")) {
                    score = Math.max(score, 95);
                  }
                  if (text.includes(item.label)) {
                    score = Math.max(score, 70);
                  }
                  let tokenHits = 0;
                  for (const token of item.tokens) {
                    if (text.includes(token)) tokenHits += 1;
                  }
                  if (tokenHits) {
                    score = Math.max(score, 20 + tokenHits * 12);
                  }
                }
                if (!score) continue;
                const candidate = {
                  node,
                  text: rawText,
                  score,
                  textLength: rawText.length,
                };
                if (
                  !best ||
                  candidate.score > best.score ||
                  (candidate.score === best.score && candidate.textLength < best.textLength)
                ) {
                  best = candidate;
                }
              }
              if (!best) return null;
              best.node.scrollIntoView({ block: "center", inline: "center" });
              if (typeof best.node.click === "function") {
                best.node.click();
              }
              for (const eventName of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
                best.node.dispatchEvent(new MouseEvent(eventName, { bubbles: true, cancelable: true, view: window }));
              }
              return (best.text || "").trim();
            }
            """,
            cleaned_labels,
        )
        if result:
            await page.wait_for_timeout(1200)
            return str(result).strip()
        return None

    async def _click_visible_text_candidate(self, page, labels: list[str]) -> str | None:
        controls = await self._iter_controls_for_labels(page, labels)
        if controls:
            locator = page.locator(self._POINT_CONTROL_SELECTOR)
            best_idx, best_text, _ = sorted(controls, key=lambda item: (-item[2], len(item[1]), item[0]))[0]
            target = locator.nth(best_idx)
            try:
                await target.scroll_into_view_if_needed()
                await target.click(timeout=2500)
                await page.wait_for_timeout(1200)
                logger.info("Blanks control clicked via playwright index=%s text=%s", best_idx, best_text)
                return best_text
            except Exception as exc:
                logger.info("Blanks playwright click failed index=%s text=%s error=%s", best_idx, best_text, exc)
                try:
                    await target.click(timeout=2500, force=True)
                    await page.wait_for_timeout(1200)
                    logger.info("Blanks control clicked via playwright force index=%s text=%s", best_idx, best_text)
                    return best_text
                except Exception as force_exc:
                    logger.info("Blanks forced playwright click failed index=%s text=%s error=%s", best_idx, best_text, force_exc)

        return await self._dispatch_visible_text_candidate_click(page, labels)

    async def _iter_point_controls(self, page, point_name: str, max_items: int = 220) -> list[tuple[int, str, int]]:
        locator = page.locator(self._POINT_CONTROL_SELECTOR)
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
            if len(re.findall(r"\(\d+\)", normalized)) > 1:
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

    async def _visible_point_control_meta(self, page, limit: int = 12) -> list[dict]:
        items = await page.evaluate(
            """
            (selector) => {
              const normalize = (value) => (value || "").replace(/\\s+/g, " ").trim();
              const isVisible = (node) => {
                if (!(node instanceof Element)) return false;
                const style = window.getComputedStyle(node);
                if (!style || style.display === "none" || style.visibility === "hidden" || style.opacity === "0") {
                  return false;
                }
                const rect = node.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
              };
              return Array.from(document.querySelectorAll(selector))
                .filter((node) => isVisible(node))
                .map((node) => ({
                  text: normalize(node.innerText || node.textContent || ""),
                  tag: (node.tagName || "").toLowerCase(),
                  role: normalize(node.getAttribute("role") || ""),
                  href: normalize(node.getAttribute("href") || ""),
                  className: normalize(typeof node.className === "string" ? node.className : ""),
                }))
                .filter((item) => item.text && item.text.length <= 160);
            }
            """,
            self._POINT_CONTROL_SELECTOR,
        )
        seen: list[dict] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            text = re.sub(r"\s+", " ", str(item.get("text") or "").strip())
            if not text:
                continue
            if any(existing["text"] == text for existing in seen):
                continue
            seen.append(
                {
                    "text": text,
                    "tag": str(item.get("tag") or "").strip(),
                    "role": str(item.get("role") or "").strip(),
                    "href": str(item.get("href") or "").strip(),
                    "className": str(item.get("className") or "").strip()[:120],
                }
            )
            if len(seen) >= limit:
                break
        return seen

    async def _open_point_menu_if_needed(self, page) -> str | None:
        openers = [
            "Выбрать точку продаж",
            "Точка продаж",
            "Точка",
            "Выберите точку",
            "Ресторан",
            "Подразделение",
            "Филиал",
            "Сменить точку",
        ]
        clicked_text = await self._click_visible_text_candidate(page, openers)
        if clicked_text:
            control_meta = await self._visible_point_control_meta(page)
            logger.info("Blanks point opener clicked via dom text=%s url=%s controls=%s", clicked_text, page.url, control_meta[:8])
            return clicked_text
        for candidate in openers:
            selectors = [
                f"button:has-text('{candidate}')",
                f"[role='button']:has-text('{candidate}')",
                f"text={candidate}",
            ]
            for selector in selectors:
                locator = page.locator(selector)
                count = await locator.count()
                if count == 0:
                    continue
                for idx in range(count):
                    item = locator.nth(idx)
                    try:
                        if not await item.is_visible():
                            continue
                        await item.click(timeout=2500, force=True)
                        await page.wait_for_timeout(1200)
                        logger.info("Blanks point opener clicked=%s selector=%s index=%s", candidate, selector, idx)
                        return
                    except Exception as exc:
                        logger.info(
                            "Blanks point opener click failed candidate=%s selector=%s index=%s error=%s",
                            candidate,
                            selector,
                            idx,
                            exc,
                        )
                        continue
        return None

    async def _click_point_variant_if_visible(self, page, point_name: str) -> str | None:
        controls = [
            item
            for item in await self._iter_point_controls(page, point_name)
            if item[2] > 0
        ]
        if controls:
            locator = page.locator(self._POINT_CONTROL_SELECTOR)
            best_idx, best_text, best_score = sorted(
                controls,
                key=lambda item: (
                    -item[2],
                    -self._point_specificity_score(item[1], point_name),
                    -len(item[1]),
                    item[0],
                ),
            )[0]
            try:
                await locator.nth(best_idx).scroll_into_view_if_needed()
                await locator.nth(best_idx).click(timeout=2500, force=True)
                await page.wait_for_timeout(1000)
                logger.info(
                    "Blanks point selected via scored control idx=%s text=%s score=%s specificity=%s",
                    best_idx,
                    best_text,
                    best_score,
                    self._point_specificity_score(best_text, point_name),
                )
                return best_text
            except Exception as exc:
                logger.info(
                    "Blanks scored point click failed idx=%s text=%s error=%s",
                    best_idx,
                    best_text,
                    exc,
                )

        for candidate in self._point_variants(point_name):
            for exact in (True, False):
                locator = page.get_by_text(candidate, exact=exact)
                count = await locator.count()
                if count == 0:
                    continue
                for idx in range(count):
                    item = locator.nth(idx)
                    try:
                        if not await item.is_visible():
                            continue
                        await item.scroll_into_view_if_needed()
                        await item.click(timeout=2500, force=True)
                        await page.wait_for_timeout(900)
                        logger.info("Blanks point selected via locator text=%s exact=%s index=%s", candidate, exact, idx)
                        return candidate
                    except Exception as exc:
                        logger.info(
                            "Blanks point locator click failed text=%s exact=%s index=%s error=%s",
                            candidate,
                            exact,
                            idx,
                            exc,
                        )
        return None

    async def _ensure_point_menu_collapsed(self, page, point_name: str) -> tuple[bool, list[str]]:
        visible_controls = await self._visible_point_controls(page, point_name)
        if not self._point_menu_looks_open(visible_controls):
            return True, visible_controls

        for action_name in ("escape", "outside_click", "opener_click"):
            try:
                if action_name == "escape":
                    await page.keyboard.press("Escape")
                elif action_name == "outside_click":
                    await page.mouse.click(20, 20)
                else:
                    await self._click_visible_text_candidate(page, ["Выбрать точку продаж", "Точка продаж"])
                await page.wait_for_timeout(900)
            except Exception:
                pass

            visible_controls = await self._visible_point_controls(page, point_name)
            if not self._point_menu_looks_open(visible_controls):
                logger.info("Blanks point menu collapsed via action=%s", action_name)
                return True, visible_controls

        logger.info("Blanks point menu still open controls=%s", visible_controls[:10])
        return False, visible_controls

    async def _search_point_if_possible(self, page, point_name: str) -> str | None:
        queries = []
        for variant in self._point_variants(point_name):
            city = variant.split(",")[0].strip()
            if city and city not in queries:
                queries.append(city)
        for selector in self._POINT_SEARCH_SELECTORS:
            locator = page.locator(selector)
            count = await locator.count()
            for idx in range(count):
                field = locator.nth(idx)
                try:
                    if not await field.is_visible():
                        continue
                    for query in queries[:2]:
                        await field.click(timeout=2000)
                        await field.fill("")
                        await field.fill(query)
                        await page.wait_for_timeout(800)
                        logger.info("Blanks point search selector=%s index=%s query=%s", selector, idx, query)
                        return query
                except Exception:
                    continue
        return None

    async def _type_point_query_via_keyboard(self, page, point_name: str) -> str | None:
        queries = []
        for variant in self._point_variants(point_name):
            city = variant.split(",")[0].strip()
            if city and city not in queries:
                queries.append(city)
        for query in queries[:2]:
            try:
                await page.keyboard.press("Control+A")
            except Exception:
                pass
            try:
                await page.keyboard.press("Delete")
            except Exception:
                pass
            try:
                await page.keyboard.type(query, delay=40)
                await page.wait_for_timeout(900)
                logger.info("Blanks point search via keyboard query=%s", query)
                return query
            except Exception:
                continue
        return None

    async def _probe_sidebar_routes_for_point(self, page, point_name: str) -> tuple[str | None, list[str], str | None, str | None]:
        visible_point_controls: list[str] = []
        opener_text: str | None = None
        search_query: str | None = None
        for label in ["Стоп-Лист", "Заказы", "Новые заказы"]:
            clicked = await self._click_visible_text_candidate(page, [label])
            if not clicked:
                continue
            await page.wait_for_timeout(1200)
            visible_point_controls = await self._visible_point_controls(page, point_name)
            control_meta = await self._visible_point_control_meta(page)
            logger.info(
                "Blanks sidebar probe label=%s url=%s controls=%s meta=%s",
                label,
                page.url,
                visible_point_controls[:8],
                control_meta[:8],
            )
            opener_text = await self._open_point_menu_if_needed(page)
            matched_point = await self._click_point_variant_if_visible(page, point_name)
            if matched_point:
                return matched_point, visible_point_controls, opener_text, search_query
            search_query = await self._search_point_if_possible(page, point_name)
            if search_query:
                matched_point = await self._click_point_variant_if_visible(page, point_name)
                if matched_point:
                    return matched_point, visible_point_controls, opener_text, search_query
            if opener_text:
                search_query = search_query or await self._type_point_query_via_keyboard(page, point_name)
                if search_query:
                    matched_point = await self._click_point_variant_if_visible(page, point_name)
                    if matched_point:
                        return matched_point, visible_point_controls, opener_text, search_query
        return None, visible_point_controls, opener_text, search_query

    async def _click_best_point_candidate(self, page, point_name: str) -> tuple[str | None, list[str]]:
        controls = await self._iter_point_controls(page, point_name)
        visible_controls = []
        best_idx = None
        best_text = None
        best_score = 0
        locator = page.locator(self._POINT_CONTROL_SELECTOR)
        for idx, text, _ in controls:
            if self._is_point_menu_control(text):
                try:
                    await locator.nth(idx).click(timeout=2500, force=True)
                    await page.wait_for_timeout(1200)
                    logger.info("Blanks point control clicked via generic scan text=%s idx=%s", text, idx)
                    controls = await self._iter_point_controls(page, point_name)
                    break
                except Exception as exc:
                    logger.info("Blanks point control click failed text=%s idx=%s error=%s", text, idx, exc)
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
        try:
            await locator.nth(best_idx).scroll_into_view_if_needed()
            await locator.nth(best_idx).click(timeout=2500, force=True)
            await page.wait_for_timeout(900)
            return best_text, visible_controls[:12]
        except Exception as exc:
            logger.info("Blanks point candidate click failed idx=%s text=%s error=%s", best_idx, best_text, exc)
            return None, visible_controls[:12]

    async def _select_point(self, page, point_name: str) -> dict:
        matched_point = await self._click_point_variant_if_visible(page, point_name)
        visible_point_controls: list[str] = []
        opener_text: str | None = None
        search_query: str | None = None
        if matched_point is None:
            visible_point_controls = await self._visible_point_controls(page, point_name)
            opener_text = await self._open_point_menu_if_needed(page)
            matched_point = await self._click_point_variant_if_visible(page, point_name)
        if matched_point is None:
            search_query = await self._search_point_if_possible(page, point_name)
            if search_query:
                matched_point = await self._click_point_variant_if_visible(page, point_name)
        if matched_point is None and opener_text:
            search_query = search_query or await self._type_point_query_via_keyboard(page, point_name)
            if search_query:
                matched_point = await self._click_point_variant_if_visible(page, point_name)
        if matched_point is None and visible_point_controls:
            matched_point, probed_controls, probed_opener, probed_query = await self._probe_sidebar_routes_for_point(page, point_name)
            if probed_controls:
                visible_point_controls = probed_controls
            opener_text = opener_text or probed_opener
            search_query = search_query or probed_query
        if matched_point is None:
            matched_point, visible_point_controls = await self._click_best_point_candidate(page, point_name)
        else:
            visible_point_controls = await self._visible_point_controls(page, point_name)
        point_menu_collapsed = False
        if matched_point is not None:
            point_menu_collapsed, visible_point_controls = await self._ensure_point_menu_collapsed(page, point_name)
            if not point_menu_collapsed:
                address = point_name.split(",")[-1].strip()
                city = point_name.split(",")[0].strip()
                retry_labels = [f"{city} {address}", address, point_name]
                retried_point = await self._click_visible_text_candidate(page, retry_labels)
                if retried_point:
                    matched_point = retried_point
                    point_menu_collapsed, visible_point_controls = await self._ensure_point_menu_collapsed(page, point_name)
        return {
            "selected": matched_point is not None,
            "matched_point": matched_point,
            "point_candidates": self._point_variants(point_name),
            "visible_point_controls": visible_point_controls,
            "opener_text": opener_text,
            "search_query": search_query,
            "point_menu_collapsed": point_menu_collapsed,
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
        if any(token in lowered for token in ["bad gateway", "502", "invalid response from the upstream server", "upstream", "gateway timeout"]):
            return "Портал временно недоступен: upstream вернул ошибку 502/Bad Gateway."
        return None

    def _looks_like_login_page(self, text: str) -> bool:
        lowered = self._normalize_text(text)
        login_markers = ["логин", "пароль", "войти", "login", "password", "remember me"]
        return sum(1 for marker in login_markers if marker in lowered) >= 2

    async def _wait_for_post_login_state(self, page, attempts: int = 8, delay_ms: int = 800) -> tuple[str, str]:
        last_text = ""
        for _ in range(max(1, attempts)):
            await page.wait_for_timeout(delay_ms)
            try:
                last_text = await page.locator("body").inner_text()
            except Exception:
                last_text = ""
            issue = self._detect_terminal_issue(last_text)
            if issue:
                return "issue", last_text
            current_url = page.url or ""
            if "/login" not in current_url.lower():
                return "ok", last_text
            if not self._looks_like_login_page(last_text):
                return "ok", last_text
            try:
                password_fields = page.locator("input[name='password'], input[type='password']")
                if await password_fields.count() == 0:
                    return "ok", last_text
            except Exception:
                return "ok", last_text
        return "login_page", last_text

    async def _wait_for_portal_ready(self, page, point_name: str, attempts: int = 8, delay_ms: int = 700) -> tuple[list[str], str]:
        last_text = ""
        last_controls: list[str] = []
        for _ in range(max(1, attempts)):
            try:
                last_controls = await self._visible_point_controls(page, point_name)
            except Exception:
                last_controls = []
            if last_controls:
                return last_controls, last_text
            try:
                last_text = await page.locator("body").inner_text()
            except Exception:
                last_text = ""
            await page.wait_for_timeout(delay_ms)
        return last_controls, last_text

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
        normalized = self._normalize_text(lowered)
        if "текущий бланк" in normalized:
            return ["текущий бланк"]
        if "сегодня" in normalized:
            return ["Сегодня"]
        if "сутки" in normalized or "24 часа" in normalized:
            return ["Сутки", "24 часа", "За сутки", "Последние сутки"]
        if "15 часов" in normalized:
            return ["15 часов", "15ч", "За 15 часов", "Последние 15 часов"]
        if "12 часов" in normalized:
            return ["12 часов", "12ч", "За 12 часов", "Последние 12 часов"]
        if "6 часов" in normalized:
            return ["6 часов", "6ч", "За 6 часов", "Последние 6 часов"]
        if "12 часов" in lowered:
            return ["12 часов", "12ч", "За 12 часов", "Последние 12 часов"]
        if "3 часа" in lowered:
            return ["3 часа", "3ч", "За 3 часа", "Последние 3 часа"]
        if "сутки" in lowered or "24 часа" in lowered:
            return ["Сутки", "24 часа", "За сутки", "Последние сутки"]
        hours_match = re.search(r"(\d+)\s*час", normalized)
        if hours_match:
            hours = int(hours_match.group(1))
            if hours > 0:
                return [
                    f"{hours} часов",
                    f"{hours} часа",
                    f"{hours} час",
                    f"{hours}ч",
                    f"За {hours} часов",
                    f"Последние {hours} часов",
                ]
        return []

    def _build_period_help_message(self, period_hint: str, visible_controls: list[str]) -> str:
        supported: list[str] = []
        for item in visible_controls:
            normalized = re.sub(r"\s+", " ", (item or "").strip())
            if not normalized:
                continue
            if normalized not in supported:
                supported.append(normalized)
        if not supported:
            supported = ["текущий бланк", "3 часа", "12 часов", "15 часов", "сутки"]
        return (
            f"Период «{period_hint}» сейчас не удалось применить на портале. "
            f"Попробуйте один из доступных вариантов: {', '.join(supported[:8])}."
        )

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
            if not ("час" in lowered or "сут" in lowered or "сегод" in lowered):
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

    async def _visible_report_controls(self, page, limit: int = 20) -> list[str]:
        controls = await self._visible_point_control_meta(page, limit=limit)
        return [item["text"] for item in controls if item.get("text")]

    async def _open_report_context_if_needed(self, page, point_name: str) -> dict:
        body = (await page.locator("body").inner_text())[:8000]
        visible_period_controls = await self._visible_period_controls(page)
        visible_report_controls = await self._visible_report_controls(page)
        if self._contains_report_context(body) or visible_period_controls:
            return {
                "body": body,
                "visible_period_controls": visible_period_controls,
                "visible_report_controls": visible_report_controls,
                "route_label": None,
            }

        route_labels = [
            "Бланк загрузки",
            "Бланки загрузки",
            "Отчет по перегрузкам",
            "Отчёт по перегрузкам",
            "Перегрузки",
            "Новые заказы",
            "Заказы",
            "Стоп-Лист",
            "Отчеты",
            "Отчёты",
        ]
        for label in route_labels:
            clicked_text = await self._click_visible_text_candidate(page, [label])
            if not clicked_text:
                continue
            await page.wait_for_timeout(1000)
            await self._ensure_point_menu_collapsed(page, point_name)
            body = (await page.locator("body").inner_text())[:8000]
            visible_period_controls = await self._visible_period_controls(page)
            visible_report_controls = await self._visible_report_controls(page)
            logger.info(
                "Blanks report route probe label=%s clicked=%s periods=%s controls=%s excerpt=%s",
                label,
                clicked_text,
                visible_period_controls[:8],
                visible_report_controls[:8],
                self._normalize_text(body)[:180],
            )
            if self._contains_report_context(body) or visible_period_controls:
                return {
                    "body": body,
                    "visible_period_controls": visible_period_controls,
                    "visible_report_controls": visible_report_controls,
                    "route_label": label,
                }

        return {
            "body": body,
            "visible_period_controls": visible_period_controls,
            "visible_report_controls": visible_report_controls,
            "route_label": None,
        }

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
        if best_text.strip().isdigit():
            logger.info("Blanks period click skipped ambiguous numeric control text=%s", best_text)
            return False
        try:
            await locator.nth(best_idx).click(timeout=2500)
            logger.info("Blanks period click result=%s", {"clicked": True, "text": best_text, "score": best_score})
            return True
        except Exception as exc:
            logger.info("Blanks period click failed idx=%s text=%s error=%s", best_idx, best_text, exc)
            return False

    async def _open_period_menu_if_needed(self, page) -> None:
        openers = ["15 часов", "12 часов", "6 часов", "3 часа", "Сутки", "Период", "За период"]
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
        if "текущий бланк" in self._normalize_text(lowered):
            return {
                "selected": True,
                "matched_period": "текущий бланк",
                "visible_period_controls": [],
                "status": "current_blank",
            }
        candidates = self._period_candidates(lowered)
        if not candidates:
            visible_controls = await self._visible_period_controls(page)
            await self._open_period_menu_if_needed(page)
            visible_controls = await self._visible_period_controls(page)
            return {
                "selected": False,
                "matched_period": None,
                "visible_period_controls": visible_controls[:10],
                "status": "needs_period",
                "message": self._build_period_help_message(period_hint, visible_controls),
            }
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
        visible_controls = await self._visible_period_controls(page)
        if await self._click_best_period_candidate(page, candidates):
            await page.wait_for_timeout(900)
            return {
                "selected": True,
                "matched_period": candidates[0],
                "visible_period_controls": visible_controls[:10],
            }
        logger.info("Blanks period selector not found for period=%s candidates=%s", period_hint, candidates)
        supported_controls = [item.lower() for item in visible_controls]
        supported = any(
            candidate.lower() in item or item in candidate.lower()
            for candidate in candidates
            for item in supported_controls
            if item
        )
        if not supported:
            return {
                "selected": False,
                "matched_period": None,
                "visible_period_controls": visible_controls[:10],
                "status": "needs_period",
                "message": self._build_period_help_message(period_hint, visible_controls),
            }
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
                current_url = page.url
                login_state, post_login_text = await self._wait_for_post_login_state(page)
                current_url = page.url
                if login_state == "issue":
                    issue = self._detect_terminal_issue(post_login_text) or "Не удалось войти в портал."
                    return self._build_failed_result(
                        point_name,
                        issue,
                        period_hint,
                        diagnostics=self._build_diagnostics(stage, current_url, page_excerpt=self._normalize_text(post_login_text)[:400]),
                    )
                if login_state == "login_page":
                    return self._build_failed_result(
                        point_name,
                        "Не удалось войти в портал: форма авторизации осталась открыта.",
                        period_hint,
                        diagnostics=self._build_diagnostics(stage, current_url, page_excerpt=self._normalize_text(post_login_text)[:400]),
                    )
                portal_controls, portal_text = await self._wait_for_portal_ready(page, point_name)
                portal_meta = await self._visible_point_control_meta(page)
                logger.info(
                    "Blanks portal ready controls=%s meta=%s excerpt=%s",
                    portal_controls[:8],
                    portal_meta[:8],
                    self._normalize_text(portal_text)[:160],
                )
                portal_issue = self._detect_terminal_issue(portal_text)
                if portal_issue:
                    return self._build_failed_result(
                        point_name,
                        portal_issue,
                        period_hint,
                        diagnostics=self._build_diagnostics("portal_ready", page.url, page_excerpt=self._normalize_text(portal_text)[:400]),
                    )
                stage = "point_selection"
                point_result = await self._select_point(page, point_name)
                current_url = page.url
                point_selected = point_result["selected"] and point_result.get("point_menu_collapsed", False)
                if not point_selected:
                    body_text = await page.locator("body").inner_text()
                    point_selected = self._point_appears_selected(body_text, point_name) and not self._point_menu_looks_open(
                        point_result["visible_point_controls"]
                    )
                if not point_selected:
                    return self._build_failed_result(
                        point_name,
                        "Не удалось подтвердить выбор нужной точки на портале.",
                        period_hint,
                        diagnostics=self._build_diagnostics(
                            stage,
                            current_url,
                            point_selected=False,
                            point_menu_collapsed=point_result.get("point_menu_collapsed", False),
                            matched_point=point_result["matched_point"],
                            point_candidates=point_result["point_candidates"],
                            visible_point_controls=point_result["visible_point_controls"],
                            point_menu_opener=point_result["opener_text"],
                            point_search_query=point_result["search_query"],
                            page_excerpt=self._normalize_text(body_text)[:400],
                        ),
                    )
                stage = "report_navigation"
                report_context = await self._open_report_context_if_needed(page, point_name)
                current_url = page.url
                stage = "period_selection"
                period_result = await self._select_period(page, period_hint)
                if period_hint and not period_result["selected"]:
                    if period_result.get("status") == "needs_period":
                        message = period_result.get("message") or "Нужно уточнить период отчета по бланкам."
                        return {
                            "status": "needs_period",
                            "point_name": point_name,
                            "has_red_flags": False,
                            "alert_hash": None,
                            "report_text": f"Точка: {point_name}\nСтатус: {message}",
                            "period_hint": period_hint or "текущий бланк",
                            "message": message,
                            "diagnostics": self._build_diagnostics(
                                stage,
                                page.url,
                                point_selected=point_selected,
                                point_menu_collapsed=point_result.get("point_menu_collapsed", False),
                                matched_point=point_result["matched_point"],
                                visible_point_controls=point_result["visible_point_controls"],
                                point_menu_opener=point_result["opener_text"],
                                point_search_query=point_result["search_query"],
                                period_selected=False,
                                matched_period=period_result["matched_period"],
                                visible_period_controls=period_result["visible_period_controls"],
                                visible_report_controls=report_context["visible_report_controls"],
                                route_label=report_context["route_label"],
                            ),
                        }
                    return self._build_failed_result(
                        point_name,
                        "Не удалось выбрать нужный период на портале.",
                        period_hint,
                        diagnostics=self._build_diagnostics(
                            stage,
                            page.url,
                            point_selected=point_selected,
                            point_menu_collapsed=point_result.get("point_menu_collapsed", False),
                            matched_point=point_result["matched_point"],
                            visible_point_controls=point_result["visible_point_controls"],
                            point_menu_opener=point_result["opener_text"],
                            point_search_query=point_result["search_query"],
                            period_selected=False,
                            matched_period=period_result["matched_period"],
                            visible_period_controls=period_result["visible_period_controls"],
                            visible_report_controls=report_context["visible_report_controls"],
                            route_label=report_context["route_label"],
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
                            point_menu_collapsed=point_result.get("point_menu_collapsed", False),
                            matched_point=point_result["matched_point"],
                            visible_point_controls=point_result["visible_point_controls"],
                            point_menu_opener=point_result["opener_text"],
                            point_search_query=point_result["search_query"],
                            period_selected=period_result["selected"],
                            matched_period=period_result["matched_period"],
                            visible_period_controls=period_result["visible_period_controls"],
                            visible_report_controls=report_context["visible_report_controls"],
                            route_label=report_context["route_label"],
                            page_excerpt=self._normalize_text(body)[:400],
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
                            point_menu_collapsed=point_result.get("point_menu_collapsed", False),
                            matched_point=point_result["matched_point"],
                            visible_point_controls=point_result["visible_point_controls"],
                            point_menu_opener=point_result["opener_text"],
                            point_search_query=point_result["search_query"],
                            period_selected=period_result["selected"],
                            matched_period=period_result["matched_period"],
                            visible_period_controls=period_result["visible_period_controls"],
                            visible_report_controls=report_context["visible_report_controls"],
                            route_label=report_context["route_label"],
                            page_excerpt=self._normalize_text(body)[:400],
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
                            point_menu_collapsed=point_result.get("point_menu_collapsed", False),
                            matched_point=point_result["matched_point"],
                            visible_point_controls=point_result["visible_point_controls"],
                            point_menu_opener=point_result["opener_text"],
                            point_search_query=point_result["search_query"],
                            period_selected=period_result["selected"],
                            matched_period=period_result["matched_period"],
                            visible_period_controls=period_result["visible_period_controls"],
                            visible_report_controls=report_context["visible_report_controls"],
                            route_label=report_context["route_label"],
                            page_excerpt=self._normalize_text(body)[:400],
                        ),
                    )
                point_specific_body, matched_point_rows = self._extract_point_specific_body(body, point_name)
                if not matched_point_rows:
                    return self._build_failed_result(
                        point_name,
                        "Не удалось подтвердить, что отчет относится к выбранной точке.",
                        period_hint,
                        diagnostics=self._build_diagnostics(
                            stage,
                            page.url,
                            point_selected=point_selected,
                            point_menu_collapsed=point_result.get("point_menu_collapsed", False),
                            matched_point=point_result["matched_point"],
                            visible_point_controls=point_result["visible_point_controls"],
                            point_menu_opener=point_result["opener_text"],
                            point_search_query=point_result["search_query"],
                            period_selected=period_result["selected"],
                            matched_period=period_result["matched_period"],
                            visible_period_controls=period_result["visible_period_controls"],
                            visible_report_controls=report_context["visible_report_controls"],
                            route_label=report_context["route_label"],
                            page_excerpt=self._normalize_text(body)[:400],
                        ),
                    )
                body = point_specific_body or body
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
                        point_menu_collapsed=point_result.get("point_menu_collapsed", False),
                        matched_point=point_result["matched_point"],
                        visible_point_controls=point_result["visible_point_controls"],
                        point_menu_opener=point_result["opener_text"],
                        point_search_query=point_result["search_query"],
                        period_selected=period_result["selected"],
                        matched_period=period_result["matched_period"],
                        visible_period_controls=period_result["visible_period_controls"],
                        visible_report_controls=report_context["visible_report_controls"],
                        route_label=report_context["route_label"],
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
