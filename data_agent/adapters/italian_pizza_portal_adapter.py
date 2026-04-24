from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from email_integration.encryption import decrypt_password

logger = logging.getLogger(__name__)
MSK_TZ = ZoneInfo("Europe/Moscow")
YEKATERINBURG_TZ = ZoneInfo("Asia/Yekaterinburg")


class ItalianPizzaPortalAdapter:
    _POINT_CONTROL_SELECTOR = "button, [role='button'], [role='option'], [role='tab'], [role='menuitem'], label, span, div, li, option, a"
    _STRICT_RED_ATTR_RE = re.compile(
        r"\b(red|danger|error|critical|alarm|negative|alert)\b",
        flags=re.IGNORECASE,
    )
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

    def _point_group_variants(self, point_name: str) -> list[str]:
        city = point_name.split(",")[0].strip()
        variants: list[str] = []
        for raw in (f"{city} (1)", city):
            normalized = re.sub(r"\s+", " ", (raw or "").strip())
            if normalized and normalized not in variants:
                variants.append(normalized)
        return variants

    def _point_address_variants(self, point_name: str) -> list[str]:
        address = point_name.split(",")[-1].strip()
        variants: list[str] = []
        seeds = [address]
        parts = re.split(r"\s+", address)
        if len(parts) >= 2 and any(ch.isdigit() for ch in parts[-1]):
            street = " ".join(parts[:-1]).strip()
            house = parts[-1].strip()
            seeds.extend(
                [
                    f"{street}, {house}",
                    f"{street},{house}",
                    f"{street} {house}",
                ]
            )
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

    def _point_header_matches_requested_point(self, text: str, point_name: str) -> bool:
        lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
        top_lines = lines[:12]
        return any(self._line_mentions_requested_point(line, point_name) for line in top_lines)

    def _blank_hour_value(self, period_hint: str) -> str | None:
        normalized = self._normalize_text(period_hint)
        if not normalized or "текущий бланк" in normalized:
            return None
        hours_match = re.search(r"(\d+)\s*час", normalized)
        if not hours_match:
            return None
        hours = int(hours_match.group(1))
        if hours in {0, 3, 6, 9, 12, 15, 18, 21}:
            return str(hours)
        return None

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

    def _point_selection_confirmed(self, point_result: dict, body_text: str, point_name: str) -> bool:
        visible_controls = point_result.get("visible_point_controls") or []
        matched_point = str(point_result.get("matched_point") or "").strip()
        body_text = body_text or ""

        header_match = self._point_header_matches_requested_point(body_text, point_name)
        body_match = self._body_mentions_requested_point(body_text, point_name)
        matched_label_match = self._line_mentions_requested_point(matched_point, point_name)
        matched_label_specific = self._point_specificity_score(matched_point, point_name) >= 3
        menu_open = self._point_menu_looks_open(visible_controls)

        if point_result.get("selected") and (header_match or body_match or matched_label_match or matched_label_specific):
            return True

        if (header_match or body_match) and not menu_open:
            return True

        return False

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

    async def _iter_sidebar_point_buttons(self, page, max_items: int = 40) -> list[tuple[int, str, str]]:
        locator = page.locator(".ESSidebarItem-button")
        count = min(await locator.count(), max_items)
        results: list[tuple[int, str, str]] = []
        for idx in range(count):
            item = locator.nth(idx)
            try:
                if not await item.is_visible():
                    continue
                text = (await item.inner_text()).strip()
                tag = await item.evaluate("(node) => (node.tagName || '').toLowerCase()")
            except Exception:
                continue
            if not text or len(text) > 120:
                continue
            results.append((idx, re.sub(r"\s+", " ", text), str(tag or "").strip().lower()))
        return results

    async def _click_sidebar_point_button(
        self,
        page,
        labels: list[str],
        *,
        preferred_tags: set[str] | None = None,
    ) -> str | None:
        buttons = await self._iter_sidebar_point_buttons(page)
        if not buttons:
            return None

        best_idx = None
        best_text = ""
        best_score = 0
        for idx, text, tag in buttons:
            score = self._label_match_score(text, labels)
            if score <= 0:
                continue
            if preferred_tags and tag in preferred_tags:
                score += 30
            if tag == "a":
                score += 8
            elif tag == "div":
                score += 4
            if score > best_score:
                best_idx = idx
                best_text = text
                best_score = score

        if best_idx is None:
            return None

        locator = page.locator(".ESSidebarItem-button")
        try:
            await locator.nth(best_idx).scroll_into_view_if_needed()
            await locator.nth(best_idx).click(timeout=2500, force=True)
            await page.wait_for_timeout(900)
            logger.info(
                "Blanks sidebar point button clicked idx=%s text=%s score=%s preferred_tags=%s",
                best_idx,
                best_text,
                best_score,
                sorted(preferred_tags or []),
            )
            return best_text
        except Exception as exc:
            logger.info(
                "Blanks sidebar point button click failed idx=%s text=%s error=%s",
                best_idx,
                best_text,
                exc,
            )
            return None

    async def _click_sidebar_point_path(self, page, point_name: str) -> str | None:
        city_clicked = await self._click_sidebar_point_button(
            page,
            self._point_group_variants(point_name),
            preferred_tags={"div"},
        )
        if not city_clicked:
            return None

        await page.wait_for_timeout(900)
        address_clicked = await self._click_sidebar_point_button(
            page,
            self._point_address_variants(point_name),
            preferred_tags={"a"},
        )
        if not address_clicked:
            return None

        await page.wait_for_timeout(1200)
        logger.info(
            "Blanks point selected via sidebar path city=%s address=%s",
            city_clicked,
            address_clicked,
        )
        return address_clicked

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
        matched_sidebar_path = await self._click_sidebar_point_path(page, point_name)
        if matched_sidebar_path:
            return matched_sidebar_path

        matched_sidebar_address = await self._click_sidebar_point_button(
            page,
            self._point_address_variants(point_name),
            preferred_tags={"a"},
        )
        if matched_sidebar_address:
            return matched_sidebar_address

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

    async def _press_login_password_enter(self, page) -> bool:
        for selector in ["input[type='password']", "input[name='password']"]:
            locator = page.locator(selector)
            if await locator.count() <= 0:
                continue
            field = locator.first
            try:
                if not await field.is_visible():
                    continue
                await field.press("Enter")
                return True
            except Exception as exc:
                logger.info("Blanks login submit via Enter failed selector=%s error=%s", selector, exc)
        return False

    async def _trigger_login_submit(self, page, *, use_force: bool = False, use_enter: bool = False) -> bool:
        clicked = False
        for selector in ["button[type='submit']", "button:has-text('Войти')", "button:has-text('Login')"]:
            locator = page.locator(selector)
            if await locator.count() <= 0:
                continue
            button = locator.first
            try:
                if not await button.is_visible():
                    continue
                await button.click(timeout=3500, force=use_force)
                clicked = True
                if not use_enter:
                    return True
                break
            except Exception as exc:
                logger.info("Blanks login submit click failed selector=%s error=%s", selector, exc)

        if use_enter or not clicked:
            return (await self._press_login_password_enter(page)) or clicked

        return clicked

    async def _submit_login_and_wait(self, page, attempts: int = 3) -> tuple[str, str]:
        last_state = "login_page"
        last_text = ""
        total_attempts = max(1, attempts)
        for attempt in range(total_attempts):
            await self._trigger_login_submit(
                page,
                use_force=attempt > 0,
                use_enter=attempt > 0,
            )
            last_state, last_text = await self._wait_for_post_login_state(
                page,
                attempts=5 if attempt else 6,
                delay_ms=700,
            )
            if last_state != "login_page":
                return last_state, last_text
            if attempt < total_attempts - 1:
                logger.info("Blanks login still on auth page, retrying submit attempt=%s", attempt + 2)
        if last_state == "login_page":
            logger.info("Blanks login still on auth page after submit retries, waiting extra grace window")
            grace_state, grace_text = await self._wait_for_post_login_state(
                page,
                attempts=4,
                delay_ms=900,
            )
            if grace_state != "login_page":
                return grace_state, grace_text
        return last_state, last_text

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

    async def _load_report_context(self, page, point_name: str, attempts: int = 3, delay_ms: int = 900) -> dict:
        last_context = {
            "body": "",
            "visible_period_controls": [],
            "visible_report_controls": [],
            "route_label": None,
        }
        total_attempts = max(1, attempts)
        for attempt in range(total_attempts):
            context = await self._open_report_context_if_needed(page, point_name)
            last_context = context
            body = context.get("body") or ""
            issue = self._detect_terminal_issue(body)
            if issue:
                return {**context, "status": "issue", "issue": issue}
            if self._looks_like_login_page(body):
                return {**context, "status": "login_page"}
            if self._report_context_ready(context):
                return {**context, "status": "ok"}
            if attempt < total_attempts - 1:
                await page.wait_for_timeout(delay_ms)
        return {**last_context, "status": "missing_context"}

    def _report_context_ready(self, context: dict) -> bool:
        body = context.get("body") or ""
        return self._contains_report_context(body) or bool(context.get("visible_period_controls") or [])

    async def _capture_report_context_snapshot(self, page, *, route_label: str | None = None) -> dict:
        body = (await page.locator("body").inner_text())[:8000]
        return {
            "body": body,
            "visible_period_controls": await self._visible_period_controls(page),
            "visible_report_controls": await self._visible_report_controls(page),
            "route_label": route_label,
        }

    async def _wait_for_report_context_snapshot(
        self,
        page,
        *,
        route_label: str | None,
        attempts: int = 4,
        delay_ms: int = 500,
    ) -> dict:
        last_context = {
            "body": "",
            "visible_period_controls": [],
            "visible_report_controls": [],
            "route_label": route_label,
        }
        total_attempts = max(1, attempts)
        for attempt in range(total_attempts):
            last_context = await self._capture_report_context_snapshot(page, route_label=route_label)
            if self._report_context_ready(last_context):
                return last_context
            if attempt < total_attempts - 1:
                await page.wait_for_timeout(delay_ms)
        return last_context

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

    async def _visible_blank_hour_controls(self, page) -> list[str]:
        locator = page.locator("button[data-cy^='hour-'], button")
        count = min(await locator.count(), 40)
        seen: list[str] = []
        for idx in range(count):
            item = locator.nth(idx)
            try:
                if not await item.is_visible():
                    continue
                text = (await item.inner_text()).strip()
            except Exception:
                continue
            if not re.fullmatch(r"\d{1,2}", text or ""):
                continue
            if text not in seen:
                seen.append(text)
        return seen[:12]

    async def _active_blank_hour_value(self, page) -> str | None:
        locator = page.locator("button[data-cy^='hour-'][disabled]")
        if await locator.count() <= 0:
            return None
        try:
            value = await locator.first.get_attribute("value")
            if value:
                return value.strip()
            text = (await locator.first.inner_text()).strip()
            return text or None
        except Exception:
            return None

    async def _first_blank_slot(self, page) -> str | None:
        locator = page.locator("[data-cy^='timesection-']")
        if await locator.count() <= 0:
            return None
        try:
            slot = await locator.first.get_attribute("data-cy")
        except Exception:
            return None
        if not slot:
            return None
        return slot.replace("timesection-", "").strip() or None

    def _blank_hour_values_match(self, actual: str | None, expected: str) -> bool:
        if actual is None:
            return False
        try:
            return int(str(actual).strip()) == int(str(expected).strip())
        except (TypeError, ValueError):
            return str(actual).strip() == str(expected).strip()

    async def _wait_for_blank_hour_applied(self, page, hour_value: str, timeout_ms: int = 7000) -> bool:
        target_prefix = f"T{int(hour_value):02d}:00"
        deadline = datetime.now().timestamp() + (timeout_ms / 1000)
        while datetime.now().timestamp() < deadline:
            active_value = await self._active_blank_hour_value(page)
            first_slot = await self._first_blank_slot(page)
            slot_matches = bool(first_slot and target_prefix in first_slot)
            active_matches = self._blank_hour_values_match(active_value, hour_value)
            if slot_matches or (active_matches and not first_slot):
                return True
            await page.wait_for_timeout(350)
        return False

    async def _click_blank_hour_chip_once(self, page, hour_value: str) -> bool:
        direct = page.locator(f"button[data-cy='hour-{hour_value}']")
        if await direct.count() > 0:
            button = direct.first
            try:
                if not await button.is_visible():
                    logger.info("Blanks blank-hour chip not visible yet value=%s selector=data-cy", hour_value)
                else:
                    class_name = (await button.get_attribute("class") or "").lower()
                    if "disabled" in class_name or await button.is_disabled():
                        if await self._wait_for_blank_hour_applied(page, hour_value, timeout_ms=3500):
                            logger.info("Blanks blank-hour chip already active value=%s selector=data-cy", hour_value)
                            return True
                        logger.info("Blanks blank-hour chip active state did not match table value=%s selector=data-cy", hour_value)
                        return False
                    await button.click(timeout=3500, force=True)
                    if await self._wait_for_blank_hour_applied(page, hour_value):
                        await page.wait_for_timeout(500)
                        logger.info("Blanks blank-hour chip clicked value=%s selector=data-cy", hour_value)
                        return True
            except Exception as exc:
                logger.info("Blanks blank-hour chip click failed value=%s selector=data-cy error=%s", hour_value, exc)

        locator = page.locator("button")
        count = min(await locator.count(), 60)
        for idx in range(count):
            item = locator.nth(idx)
            try:
                if not await item.is_visible():
                    continue
                text = (await item.inner_text()).strip()
            except Exception:
                continue
            if text != hour_value:
                continue

            class_name = (await item.get_attribute("class") or "").lower()
            if "disabled" in class_name:
                if await self._wait_for_blank_hour_applied(page, hour_value, timeout_ms=3500):
                    logger.info("Blanks blank-hour chip already active value=%s idx=%s", hour_value, idx)
                    return True
                logger.info("Blanks blank-hour chip active state did not match table value=%s idx=%s", hour_value, idx)
                return False

            try:
                await item.click(timeout=2500, force=True)
                if await self._wait_for_blank_hour_applied(page, hour_value):
                    await page.wait_for_timeout(500)
                    logger.info("Blanks blank-hour chip clicked value=%s idx=%s", hour_value, idx)
                    return True
            except Exception as exc:
                logger.info("Blanks blank-hour chip click failed value=%s idx=%s error=%s", hour_value, idx, exc)
        return False

    async def _click_blank_hour_chip(self, page, hour_value: str, attempts: int = 3) -> bool:
        total_attempts = max(1, attempts)
        for attempt in range(total_attempts):
            if await self._click_blank_hour_chip_once(page, hour_value):
                return True
            if attempt < total_attempts - 1:
                await page.wait_for_timeout(500 + (attempt * 250))
        return False

    async def _ensure_blank_hour_chip_selected(self, page, *, point_name: str, hour_value: str) -> tuple[bool, list[str]]:
        if await self._click_blank_hour_chip(page, hour_value):
            return True, await self._visible_blank_hour_controls(page)

        logger.info(
            "Blanks blank-hour chip did not apply value=%s, reloading report context for point=%s",
            hour_value,
            point_name,
        )
        report_context = await self._load_report_context(page, point_name, attempts=2, delay_ms=700)
        visible_controls = list(report_context.get("visible_period_controls") or [])
        if report_context.get("status") == "ok" and await self._click_blank_hour_chip(page, hour_value, attempts=2):
            refreshed_controls = await self._visible_blank_hour_controls(page)
            return True, refreshed_controls or visible_controls
        if not visible_controls:
            visible_controls = await self._visible_blank_hour_controls(page)
        return False, visible_controls

    def _rolling_blank_hours(self, period_hint: str) -> int | None:
        normalized = self._normalize_text(period_hint)
        if not normalized or "текущий бланк" in normalized:
            return None
        if "сутки" in normalized or "24 часа" in normalized:
            return 24
        match = re.search(r"(\d+)\s*час", normalized)
        if not match:
            return None
        try:
            hours = int(match.group(1))
        except ValueError:
            return None
        return hours if hours > 0 else None

    def _blank_hour_scan_values(self, period_hint: str, reference_time: datetime | None = None) -> list[str]:
        rolling_hours = self._rolling_blank_hours(period_hint)
        if not rolling_hours:
            return []

        reference = reference_time or datetime.now(MSK_TZ)
        day_start = reference.replace(hour=0, minute=0, second=0, microsecond=0)
        range_start = reference - timedelta(hours=rolling_hours)
        values: list[str] = []
        for hour in range(0, 24, 3):
            window_start = day_start + timedelta(hours=hour)
            window_end = window_start + timedelta(hours=3)
            if window_end <= range_start or window_start >= reference:
                continue
            values.append(str(hour))
        if values:
            return values
        current_hour = max(0, min(21, (reference.hour // 3) * 3))
        return [str(current_hour)]

    def _coerce_blank_reference_time(
        self,
        reference_time: datetime | None,
        timezone: ZoneInfo = YEKATERINBURG_TZ,
    ) -> datetime:
        if reference_time is None:
            return datetime.now(timezone)
        if reference_time.tzinfo is None:
            return reference_time.replace(tzinfo=timezone)
        return reference_time.astimezone(timezone)

    def _blank_signal_time_window(
        self,
        signal: dict,
        *,
        reference_time: datetime,
    ) -> tuple[datetime, datetime] | None:
        base_date = reference_time.date()
        slot_id = str(signal.get("slot_id") or "").strip()
        if slot_id:
            for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
                try:
                    parsed_slot = datetime.strptime(slot_id, fmt).replace(tzinfo=reference_time.tzinfo)
                    base_date = parsed_slot.date()
                    break
                except ValueError:
                    continue

        time_range = str(signal.get("time_range") or "").strip()
        match = re.search(r"(\d{1,2}):(\d{2})\s*[-–—]\s*(\d{1,2}):(\d{2})", time_range)
        if not match:
            return None

        start_hour, start_minute, end_hour, end_minute = (int(part) for part in match.groups())
        slot_start = datetime(
            base_date.year,
            base_date.month,
            base_date.day,
            start_hour,
            start_minute,
            tzinfo=reference_time.tzinfo,
        )
        slot_end = datetime(
            base_date.year,
            base_date.month,
            base_date.day,
            end_hour,
            end_minute,
            tzinfo=reference_time.tzinfo,
        )
        if slot_end <= slot_start:
            slot_end += timedelta(days=1)
        return slot_start, slot_end

    def _filter_blank_signals_to_rolling_window(
        self,
        signals: list[dict],
        *,
        period_hint: str,
        reference_time: datetime | None = None,
    ) -> list[dict]:
        rolling_hours = self._rolling_blank_hours(period_hint)
        if not rolling_hours:
            return list(signals)

        reference = self._coerce_blank_reference_time(reference_time)
        range_start = reference - timedelta(hours=rolling_hours)
        filtered: list[dict] = []
        for signal in signals:
            time_window = self._blank_signal_time_window(signal, reference_time=reference)
            if time_window is None:
                filtered.append(signal)
                continue
            slot_start, slot_end = time_window
            if slot_end > range_start and slot_start < reference:
                filtered.append(signal)
        return filtered

    async def _read_blank_red_signals(self, page) -> dict:
        return await page.evaluate(
            """
() => {
  const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
  const parseRgb = (value) => {
    const match = String(value || "").match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/i);
    return match ? match.slice(1, 4).map(Number) : null;
  };
  const hasRedDominance = (rgb) => {
    if (!rgb) return false;
    const [r, g, b] = rgb;
    return r >= 150 && r - Math.max(g, b) >= 25 && g <= 220 && b <= 220;
  };
  const styleLooksRed = (style, rawStyle = "") => {
    const colors = [
      style.backgroundColor,
      style.color,
      style.borderTopColor,
      style.borderRightColor,
      style.borderBottomColor,
      style.borderLeftColor,
      style.fill,
      style.stroke,
      rawStyle,
    ];
    return colors.some((value) => hasRedDominance(parseRgb(value)));
  };
  const attrsLookRed = (node) => {
    const blob = [
      node.className || "",
      node.getAttribute?.("data-cy") || "",
      node.getAttribute?.("data-testid") || "",
      node.getAttribute?.("title") || "",
      node.getAttribute?.("aria-label") || "",
      node.getAttribute?.("style") || "",
    ].join(" ");
    return /\b(red|danger|error|critical|alarm|negative|alert)\b/i.test(blob);
  };
  const isVisuallyInteresting = (node) => {
    const style = getComputedStyle(node);
    const rawStyle = String(node.getAttribute?.("style") || "");
    const className = String(node.className || "");
    const bg = style.backgroundColor || "";
    const color = style.color || "";
    const border = style.borderTopColor || "";
    const hasNonDefaultBackground = bg && !/255, 255, 255|rgba\\(0, 0, 0, 0\\)|transparent/i.test(bg);
    const hasColoredText = hasRedDominance(parseRgb(color));
    const hasColoredBorder = hasRedDominance(parseRgb(border));
    return hasNonDefaultBackground || hasColoredText || hasColoredBorder || !!rawStyle || /jss|Mui|css-/i.test(className);
  };
  const inspectCell = (cell, rowLabel, value) => {
    const queue = [cell, ...Array.from(cell.querySelectorAll("*")).slice(0, 40)];
    for (const node of queue) {
      const style = getComputedStyle(node);
      const rawStyle = String(node.getAttribute?.("style") || "");
      if (styleLooksRed(style, rawStyle) || attrsLookRed(node)) {
        return {
          matched: true,
          sample: {
            tag: String(node.tagName || "").toLowerCase(),
            class_name: String(node.className || ""),
            data_cy: String(node.getAttribute?.("data-cy") || ""),
            background_color: style.backgroundColor || "",
            text_color: style.color || "",
            border_color: style.borderTopColor || "",
          },
        };
      }
    }
    const normalizedRow = clean(rowLabel).toLowerCase();
    const normalizedValue = clean(value).replace(",", ".");
    if (normalizedRow === "остаток") {
      const numeric = Number(normalizedValue);
      if (!Number.isNaN(numeric) && numeric <= 0) {
        return {
          matched: true,
          sample: {
            tag: String(cell.tagName || "").toLowerCase(),
            class_name: String(cell.className || ""),
            data_cy: String(cell.getAttribute?.("data-cy") || ""),
            background_color: getComputedStyle(cell).backgroundColor || "",
            text_color: getComputedStyle(cell).color || "",
            border_color: getComputedStyle(cell).borderTopColor || "",
          },
        };
      }
    }
    return { matched: false, sample: null };
  };
  const parseNumeric = (value) => {
    const match = clean(value).replace(",", ".").match(/-?\\d+(?:\\.\\d+)?/);
    if (!match) return null;
    const numeric = Number(match[0]);
    return Number.isFinite(numeric) ? numeric : null;
  };
  const pickMetricRow = (rowsMap, aliases) => {
    for (const [label, values] of rowsMap.entries()) {
      if (aliases.some((alias) => label === alias || label.includes(alias))) {
        return values;
      }
    }
    return null;
  };
  const ensureGroupedEntry = (grouped, key, payload) => {
    if (!grouped.has(key)) {
      grouped.set(key, {
        slot_id: payload.slot_id,
        service: payload.service,
        time_range: payload.time_range,
        column: payload.column,
        rows: [],
      });
    }
    return grouped.get(key);
  };

  const cards = Array.from(document.querySelectorAll("[data-cy^='timesection-']"));
  const signals = [];
  const styledCellSamples = [];
  const tableSamples = [];
  let tableCount = 0;
  for (const card of cards) {
    const slotId = clean((card.getAttribute("data-cy") || "").replace("timesection-", ""));
    const tables = Array.from(card.querySelectorAll("table"));
    tableCount += tables.length;
    let fallbackColumns = [];
    for (const table of tables) {
      const headRows = Array.from(table.tHead?.rows || []);
      const headerParts = Array.from(
        table.querySelectorAll("thead h5, thead h4, thead h3, caption, [data-cy*='header'] h5, [data-cy*='header'] h4")
      ).map((node) => clean(node.innerText)).filter(Boolean);
      const cardHeadings = Array.from(card.querySelectorAll("h5, h4, h3")).map((node) => clean(node.innerText)).filter(Boolean);
      const service = headerParts[0] || cardHeadings[0] || "";
      const timeRange = headerParts[1] || cardHeadings[1] || slotId;
      const parsedColumns = Array.from(headRows[1]?.children || [])
        .filter((node) => String(node.tagName || "").toLowerCase() === "th")
        .slice(1)
        .map((node) => clean(node.innerText));
      const hasNamedColumns = parsedColumns.some((item) => item);
      const columns = hasNamedColumns ? parsedColumns : fallbackColumns;
      if (hasNamedColumns) {
        fallbackColumns = parsedColumns;
      }
      const grouped = new Map();
      const metricRows = new Map();

      const bodyRows = Array.from(table.tBodies || []).flatMap((section) => Array.from(section.rows || []));
      for (const tr of bodyRows) {
        const tds = Array.from(tr.children || []).filter((node) => String(node.tagName || "").toLowerCase() === "td");
        if (!tds.length) continue;
        const rowLabel = clean(tds[0].innerText);
        const normalizedRowLabel = clean(rowLabel).toLowerCase();
        if (!metricRows.has(normalizedRowLabel)) {
          metricRows.set(normalizedRowLabel, new Map());
        }
        tds.slice(1).forEach((td, idx) => {
          const column = columns[idx] || `Колонка ${idx + 1}`;
          const value = clean(td.innerText);
          metricRows.get(normalizedRowLabel).set(column, {
            row_label: rowLabel,
            value,
          });
          if (styledCellSamples.length < 20 && isVisuallyInteresting(td)) {
            styledCellSamples.push({
              slot_id: slotId,
              service,
              time_range: timeRange,
              column,
              row_label: rowLabel,
              value,
              tag: String(td.tagName || "").toLowerCase(),
              class_name: String(td.className || ""),
              data_cy: String(td.getAttribute?.("data-cy") || ""),
              background_color: getComputedStyle(td).backgroundColor || "",
              text_color: getComputedStyle(td).color || "",
              border_color: getComputedStyle(td).borderTopColor || "",
            });
          }
          const cellMatch = inspectCell(td, rowLabel, value);
          if (!cellMatch.matched) {
            return;
          }
          if (styledCellSamples.length < 20) {
            styledCellSamples.push({
              slot_id: slotId,
              service,
              time_range: timeRange,
              column,
              row_label: rowLabel,
              value,
              ...cellMatch.sample,
            });
          }

          const key = `${service}|${timeRange}|${column}`;
          ensureGroupedEntry(grouped, key, {
            slot_id: slotId,
            service,
            time_range: timeRange,
            column,
          }).rows.push({
            row_label: rowLabel,
            value,
            background_color: cellMatch.sample?.background_color || "",
            text_color: cellMatch.sample?.text_color || "",
            border_color: cellMatch.sample?.border_color || "",
            class_name: cellMatch.sample?.class_name || "",
            data_cy: cellMatch.sample?.data_cy || "",
            matched_tag: cellMatch.sample?.tag || "",
          });
        });
      }

      const maxRow = pickMetricRow(metricRows, ["макс", "максимум", "лимит"]);
      const acceptedRow = pickMetricRow(metricRows, ["принято"]);
      const remainingRow = pickMetricRow(metricRows, ["остаток"]);
      const metricColumns = new Set([
        ...Array.from(maxRow?.keys() || []),
        ...Array.from(acceptedRow?.keys() || []),
        ...Array.from(remainingRow?.keys() || []),
      ]);
      if (tableSamples.length < 12) {
        tableSamples.push({
          slot_id: slotId,
          service,
          time_range: timeRange,
          columns: Array.from(metricColumns),
          rows: Array.from(metricRows.values()).slice(0, 4).map((values) => {
            const items = Array.from(values.values());
            return {
              row_label: items[0]?.row_label || "",
              values: items.map((item) => item.value),
            };
          }),
        });
      }
      for (const column of metricColumns) {
        const maxCell = maxRow?.get(column);
        const acceptedCell = acceptedRow?.get(column);
        const remainingCell = remainingRow?.get(column);
        const maxValue = parseNumeric(maxCell?.value);
        const acceptedValue = parseNumeric(acceptedCell?.value);
        const remainingValue = parseNumeric(remainingCell?.value);

        if (
          acceptedCell &&
          maxCell &&
          maxValue !== null &&
          acceptedValue !== null &&
          (acceptedValue > maxValue || (maxValue <= 0 && acceptedValue > 0))
        ) {
          const key = `${service}|${timeRange}|${column}`;
          const entry = ensureGroupedEntry(grouped, key, {
            slot_id: slotId,
            service,
            time_range: timeRange,
            column,
          });
          entry.rows.push({
            row_label: maxCell.row_label,
            value: maxCell.value,
            inferred_rule: "accepted_gt_max",
          });
          entry.rows.push({
            row_label: acceptedCell.row_label,
            value: acceptedCell.value,
            inferred_rule: "accepted_gt_max",
          });
        }

        if (remainingCell && remainingValue !== null && remainingValue <= 0) {
          const key = `${service}|${timeRange}|${column}`;
          const entry = ensureGroupedEntry(grouped, key, {
            slot_id: slotId,
            service,
            time_range: timeRange,
            column,
          });
          entry.rows.push({
            row_label: remainingCell.row_label,
            value: remainingCell.value,
            inferred_rule: "remaining_non_positive",
          });
        }
      }

      for (const entry of grouped.values()) {
        signals.push(entry);
      }
    }
  }

  return {
    slot_count: cards.length,
    table_count: tableCount,
    first_slot: clean((cards[0]?.getAttribute("data-cy") || "").replace("timesection-", "")),
    signals,
    styled_cell_samples: styledCellSamples,
    table_samples: tableSamples,
  };
}
"""
        )

    def _parse_rgb_triplet(self, value: str) -> tuple[int, int, int] | None:
        match = re.search(r"rgba?\((\d+),\s*(\d+),\s*(\d+)", str(value or ""), flags=re.IGNORECASE)
        if not match:
            return None
        return tuple(int(part) for part in match.groups())

    def _rgb_looks_red(self, value: str) -> bool:
        rgb = self._parse_rgb_triplet(value)
        if not rgb:
            return False
        red, green, blue = rgb
        return red >= 150 and red - max(green, blue) >= 25 and green <= 220 and blue <= 220

    def _blank_row_has_red_evidence(self, row: dict) -> bool:
        if row.get("inferred_rule"):
            return True

        color_fields = [
            row.get("background_color"),
            row.get("text_color"),
            row.get("border_color"),
        ]
        if any(self._rgb_looks_red(value) for value in color_fields if value):
            return True

        attr_blob = " ".join(
            str(value or "")
            for value in (
                row.get("class_name"),
                row.get("data_cy"),
                row.get("matched_tag"),
            )
        )
        return bool(self._STRICT_RED_ATTR_RE.search(attr_blob))

    def _parse_blank_metric_value(self, value: str | None) -> float | None:
        match = re.search(r"-?\d+(?:[.,]\d+)?", str(value or ""))
        if not match:
            return None
        try:
            return float(match.group(0).replace(",", "."))
        except ValueError:
            return None

    def _is_blank_signal_actionable(self, signal: dict) -> bool:
        rows = signal.get("rows") or []
        for row in rows:
            inferred_rule = str(row.get("inferred_rule") or "").strip().lower()
            if inferred_rule == "accepted_gt_max":
                return True

            label = self._normalize_text(str(row.get("row_label") or ""))
            numeric_value = self._parse_blank_metric_value(row.get("value"))
            if numeric_value is None or numeric_value <= 0:
                continue

            if "принято" in label:
                return True
            if not label:
                return True
            if "остаток" in label:
                continue
            if "итого" in label and numeric_value <= 0:
                continue
            return True
        return False

    def _select_user_facing_blank_rows(self, rows: list[dict]) -> list[dict]:
        selected: list[dict] = []
        seen: set[tuple[str, str, str]] = set()

        for row in rows:
            label = str(row.get("row_label") or "").strip()
            normalized_label = self._normalize_text(label)
            value = str(row.get("value") or "").strip()
            numeric_value = self._parse_blank_metric_value(value)
            inferred_rule = str(row.get("inferred_rule") or "").strip().lower()

            include = False
            if inferred_rule == "accepted_gt_max":
                include = True
            elif "остаток" in normalized_label:
                include = False
            elif "принято" in normalized_label:
                include = bool(numeric_value is not None and numeric_value > 0)
            elif "макс" in normalized_label or "максимум" in normalized_label or "лимит" in normalized_label:
                include = bool(numeric_value is not None and numeric_value > 0)
            elif not normalized_label:
                include = bool(numeric_value is not None and numeric_value > 0)
            else:
                include = bool(numeric_value is not None and numeric_value > 0)

            if not include:
                continue

            dedupe_key = (normalized_label, value, inferred_rule)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            selected.append(row)

        if selected:
            return selected

        for row in rows:
            label = str(row.get("row_label") or "").strip()
            value = str(row.get("value") or "").strip()
            if not label and not value:
                continue
            return [row]
        return []

    def _filter_red_blank_signals(self, signals: list[dict]) -> list[dict]:
        filtered: list[dict] = []
        for signal in signals:
            rows = signal.get("rows") or []
            red_rows = [row for row in rows if self._blank_row_has_red_evidence(row)]
            if not red_rows:
                continue
            if not self._is_blank_signal_actionable(signal):
                continue
            cleaned_signal = dict(signal)
            cleaned_signal["rows"] = self._select_user_facing_blank_rows(red_rows)
            filtered.append(cleaned_signal)
        return filtered

    def _build_blank_report_from_signals(
        self,
        *,
        point_name: str,
        period_hint: str,
        signals: list[dict],
    ) -> tuple[str, bool]:
        period_label = period_hint or "текущий бланк"
        if not signals:
            return (
                f"📍 Точка: {point_name}\n"
                f"✅ Статус: красных зон по бланкам не найдено\n"
                f"🕒 Период: {period_label}",
                False,
            )

        lines = [
            f"📍 Точка: {point_name}",
            "🔴 Статус: найдены красные зоны по бланкам",
            f"🕒 Период: {period_label}",
            "🔴 Красные зоны:",
        ]
        for index, signal in enumerate(signals[:18], start=1):
            rows = signal.get("rows") or []
            row_parts: list[str] = []
            for row in rows[:4]:
                label = (row.get("row_label") or "").strip()
                value = (row.get("value") or "").strip()
                if label and value:
                    row_parts.append(f"{label}: {value}")
                elif value:
                    row_parts.append(value)
                elif label:
                    row_parts.append(label)
            details = "; ".join(row_parts)
            summary = (
                f"🔴 {index}. {signal.get('service') or 'Зона'} "
                f"{signal.get('time_range') or '-'} -> {signal.get('column') or '-'}"
            )
            if details:
                summary += f" ({details})"
            lines.append(summary)
        if len(signals) > 18:
            lines.append(f"🔴 И ещё {len(signals) - 18} красных зон.")
        return "\n".join(lines), True

    async def _scan_blank_report(self, page, point_name: str, period_hint: str) -> dict:
        scan_hours = self._blank_hour_scan_values(period_hint)
        inspected_hours: list[str] = []
        inspected_slots: list[str] = []
        aggregated_signals: list[dict] = []
        observed_slot_counts: list[int] = []
        observed_table_counts: list[int] = []
        styled_cell_samples: list[dict] = []
        table_samples: list[dict] = []

        if not scan_hours:
            snapshot = await self._read_blank_red_signals(page)
            filtered_signals = self._filter_red_blank_signals(snapshot.get("signals") or [])
            if snapshot.get("first_slot"):
                inspected_slots.append(snapshot["first_slot"])
            observed_slot_counts.append(int(snapshot.get("slot_count") or 0))
            observed_table_counts.append(int(snapshot.get("table_count") or 0))
            report_text, has_red_flags = self._build_blank_report_from_signals(
                point_name=point_name,
                period_hint=period_hint,
                signals=filtered_signals,
            )
            return {
                "status": "ok",
                "report_text": report_text,
                "has_red_flags": has_red_flags,
                "matched_period": "текущий бланк",
                "visible_period_controls": await self._visible_blank_hour_controls(page),
                "inspected_hours": inspected_hours,
                "inspected_slots": inspected_slots,
                "slot_count": max(observed_slot_counts or [0]),
                "table_count": max(observed_table_counts or [0]),
                "red_signal_count": len(filtered_signals),
                "styled_cell_samples": snapshot.get("styled_cell_samples") or [],
                "table_samples": snapshot.get("table_samples") or [],
            }

        for hour_value in scan_hours:
            selected, visible_controls = await self._ensure_blank_hour_chip_selected(
                page,
                point_name=point_name,
                hour_value=hour_value,
            )
            if not selected:
                return {
                    "status": "needs_period",
                    "message": self._build_period_help_message(period_hint, visible_controls),
                    "matched_period": hour_value,
                    "visible_period_controls": visible_controls,
                    "inspected_hours": inspected_hours,
                    "inspected_slots": inspected_slots,
                }
            inspected_hours.append(hour_value)
            snapshot = await self._read_blank_red_signals(page)
            if snapshot.get("first_slot"):
                inspected_slots.append(snapshot["first_slot"])
            observed_slot_counts.append(int(snapshot.get("slot_count") or 0))
            observed_table_counts.append(int(snapshot.get("table_count") or 0))
            aggregated_signals.extend(snapshot.get("signals") or [])
            for sample in snapshot.get("styled_cell_samples") or []:
                if len(styled_cell_samples) >= 20:
                    break
                styled_cell_samples.append(sample)
            for table_sample in snapshot.get("table_samples") or []:
                if len(table_samples) >= 12:
                    break
                table_samples.append(table_sample)

        unique_signals: list[dict] = []
        seen_keys: set[str] = set()
        for signal in aggregated_signals:
            key = "|".join(
                [
                    signal.get("slot_id") or "",
                    signal.get("service") or "",
                    signal.get("time_range") or "",
                    signal.get("column") or "",
                    ";".join(
                        f"{row.get('row_label') or ''}:{row.get('value') or ''}"
                        for row in (signal.get("rows") or [])
                    ),
                ]
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            unique_signals.append(signal)

        filtered_signals = self._filter_red_blank_signals(
            self._filter_blank_signals_to_rolling_window(
                unique_signals,
                period_hint=period_hint,
            )
        )
        report_text, has_red_flags = self._build_blank_report_from_signals(
            point_name=point_name,
            period_hint=period_hint,
            signals=filtered_signals,
        )
        return {
            "status": "ok",
            "report_text": report_text,
            "has_red_flags": has_red_flags,
            "matched_period": ", ".join(scan_hours),
            "visible_period_controls": await self._visible_blank_hour_controls(page),
            "inspected_hours": inspected_hours,
            "inspected_slots": inspected_slots,
            "slot_count": max(observed_slot_counts or [0]),
            "table_count": max(observed_table_counts or [0]),
            "red_signal_count": len(filtered_signals),
            "styled_cell_samples": styled_cell_samples,
            "table_samples": table_samples,
        }

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
        context = await self._capture_report_context_snapshot(page)
        if self._report_context_ready(context):
            return context

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
            await page.wait_for_timeout(700)
            await self._ensure_point_menu_collapsed(page, point_name)
            context = await self._wait_for_report_context_snapshot(
                page,
                route_label=label,
                attempts=5,
                delay_ms=450,
            )
            logger.info(
                "Blanks report route probe label=%s clicked=%s periods=%s controls=%s excerpt=%s",
                label,
                clicked_text,
                (context.get("visible_period_controls") or [])[:8],
                (context.get("visible_report_controls") or [])[:8],
                self._normalize_text(context.get("body") or "")[:180],
            )
            if self._report_context_ready(context):
                return context

        return context

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
        normalized_hint = self._normalize_text(lowered)
        if "текущий бланк" in normalized_hint:
            return {
                "selected": True,
                "matched_period": "текущий бланк",
                "visible_period_controls": [],
                "status": "current_blank",
            }
        body_text = (await page.locator("body").inner_text())[:8000]
        normalized_body = self._normalize_text(body_text)
        if "бланк загрузки" in normalized_body:
            visible_blank_hours = await self._visible_blank_hour_controls(page)
            blank_hour_value = self._blank_hour_value(period_hint)
            if blank_hour_value:
                if await self._click_blank_hour_chip(page, blank_hour_value):
                    return {
                        "selected": True,
                        "matched_period": blank_hour_value,
                        "visible_period_controls": visible_blank_hours[:10],
                        "status": "blank_hour_chip",
                    }
                return {
                    "selected": False,
                    "matched_period": None,
                    "visible_period_controls": visible_blank_hours[:10],
                    "status": "needs_period",
                    "message": self._build_period_help_message(period_hint, visible_blank_hours),
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
                current_url = page.url
                login_state, post_login_text = await self._submit_login_and_wait(page)
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
                body_text = await page.locator("body").inner_text()
                point_selected = self._point_selection_confirmed(point_result, body_text, point_name)
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
                stage = "period_selection"
                report_context = await self._load_report_context(page, point_name)
                current_url = page.url
                body = report_context.get("body") or ""
                if report_context.get("status") == "issue":
                    return self._build_failed_result(
                        point_name,
                        report_context.get("issue") or "Не удалось открыть отчет по бланкам.",
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
                            matched_period=None,
                            visible_period_controls=await self._visible_blank_hour_controls(page),
                            visible_report_controls=report_context["visible_report_controls"],
                            route_label=report_context["route_label"],
                            page_excerpt=self._normalize_text(body)[:400],
                        ),
                    )
                if report_context.get("status") == "login_page":
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
                            period_selected=False,
                            matched_period=None,
                            visible_period_controls=await self._visible_blank_hour_controls(page),
                            visible_report_controls=report_context["visible_report_controls"],
                            route_label=report_context["route_label"],
                            page_excerpt=self._normalize_text(body)[:400],
                        ),
                    )
                if report_context.get("status") != "ok":
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
                            period_selected=False,
                            matched_period=None,
                            visible_period_controls=await self._visible_blank_hour_controls(page),
                            visible_report_controls=report_context["visible_report_controls"],
                            route_label=report_context["route_label"],
                            page_excerpt=self._normalize_text(body)[:400],
                        ),
                    )
                scan_result = await self._scan_blank_report(page, point_name, period_hint)
                logger.info(
                    "Blanks scan summary point=%s period=%s red_signals=%s slot_count=%s table_count=%s samples=%s tables=%s",
                    point_name,
                    period_hint,
                    scan_result.get("red_signal_count"),
                    scan_result.get("slot_count"),
                    scan_result.get("table_count"),
                    (scan_result.get("styled_cell_samples") or [])[:5],
                    (scan_result.get("table_samples") or [])[:3],
                )
                if scan_result.get("status") == "needs_period":
                    message = scan_result.get("message") or "Нужно уточнить период отчета по бланкам."
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
                            matched_period=scan_result.get("matched_period"),
                            visible_period_controls=scan_result.get("visible_period_controls"),
                            visible_report_controls=report_context["visible_report_controls"],
                            route_label=report_context["route_label"],
                            inspected_hours=scan_result.get("inspected_hours"),
                            inspected_slots=scan_result.get("inspected_slots"),
                            slot_count=scan_result.get("slot_count"),
                            table_count=scan_result.get("table_count"),
                            red_signal_count=scan_result.get("red_signal_count"),
                            styled_cell_samples=scan_result.get("styled_cell_samples"),
                            table_samples=scan_result.get("table_samples"),
                        ),
                    }

                stage = "report_read"
                report_text = scan_result["report_text"]
                has_red_flags = scan_result["has_red_flags"]
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
                        period_selected=True,
                        matched_period=scan_result.get("matched_period"),
                        visible_period_controls=scan_result.get("visible_period_controls"),
                        visible_report_controls=report_context["visible_report_controls"],
                        route_label=report_context["route_label"],
                        inspected_hours=scan_result.get("inspected_hours"),
                        inspected_slots=scan_result.get("inspected_slots"),
                        slot_count=scan_result.get("slot_count"),
                        table_count=scan_result.get("table_count"),
                        red_signal_count=scan_result.get("red_signal_count"),
                        styled_cell_samples=scan_result.get("styled_cell_samples"),
                        table_samples=scan_result.get("table_samples"),
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
