from __future__ import annotations

import json
import logging
import re

import aiohttp

from ..italian_pizza import resolve_italian_pizza_point

logger = logging.getLogger(__name__)

_CATEGORY_STOPWORDS = {
    "пицца", "комбо", "детское меню", "десерты", "напитки", "закуски", "салаты", "соусы",
    "роллы", "бургеры", "паста", "горячее", "супы", "войти", "контакты", "доставка",
    "заказать доставку", "выберите адрес", "меню", "фильтры", "еще",
}

_ORDER_ACTION_LABELS = {
    "выбрать", "в корзину", "добавить", "заказать", "недоступно", "подробнее",
}

_DISABLED_TEXT_MARKERS = {
    "недоступно", "нет в наличии", "sold out", "unavailable",
}

_DISABLED_CLASS_MARKERS = {
    "disabled", "unavailable", "inactive", "soldout", "sold-out", "out-of-stock", "not-available", "is-disabled",
}


class ItalianPizzaPublicAdapter:
    def _normalize_text(self, text: str) -> str:
        normalized = re.sub(r"\s+", " ", (text or "").strip().lower())
        return normalized.replace("ё", "е")

    async def _fetch_public_html(self, url: str) -> str:
        timeout = aiohttp.ClientTimeout(total=30)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
            ),
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        }
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url) as response:
                response.raise_for_status()
                return await response.text()

    async def _fetch_public_json(self, url: str, *, params: dict | None = None):
        timeout = aiohttp.ClientTimeout(total=30)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
            ),
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://italianpizza.ru/",
        }
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url, params=params) as response:
                response.raise_for_status()
                return await response.json()

    def _decode_json_string(self, value: str) -> str:
        try:
            return json.loads(f'"{value}"')
        except Exception:
            return value

    def _build_diagnostics(self, stage: str, url: str, **extra) -> dict:
        diagnostics = {"stage": stage, "url": url}
        for key, value in extra.items():
            if value is None:
                continue
            diagnostics[key] = value
        return diagnostics

    def _normalize_address_match(self, value: str) -> str:
        normalized = self._normalize_text(value)
        normalized = normalized.replace("стр ", " ").replace("строение ", " ")
        normalized = normalized.replace("д ", " ").replace("дом ", " ")
        return re.sub(r"\s+", " ", normalized).strip()

    async def _resolve_public_organization(self, point) -> dict | None:
        city_query = point.city.replace("ё", "е")
        cities = await self._fetch_public_json(
            "https://italianpizza.ru/api/v3/cities",
            params={"name": city_query, "withSatellites": "true"},
        )
        if not isinstance(cities, list) or not cities:
            logger.info("Stoplist public api city not found city=%s", point.city)
            return None

        city = None
        for item in cities:
            if str(item.get("subdomain") or "").strip().lower() == point.public_slug.lower():
                city = item
                break
        if city is None:
            normalized_city = self._normalize_text(point.city)
            for item in cities:
                if self._normalize_text(str(item.get("name") or "")) == normalized_city:
                    city = item
                    break
        if city is None:
            city = cities[0]

        organizations = await self._fetch_public_json(
            "https://italianpizza.ru/api/v3/organizations",
            params={"cityId": city.get("id"), "address": ""},
        )
        if not isinstance(organizations, list) or not organizations:
            logger.info("Stoplist public api organizations not found point=%s city_id=%s", point.display_name, city.get("id"))
            return None

        target_address = self._normalize_address_match(point.address)
        best_org = None
        best_score = 0
        for org in organizations:
            score = 0
            org_name = self._normalize_address_match(str(org.get("name") or ""))
            org_address = self._normalize_address_match(str(org.get("address") or ""))
            if target_address and target_address in org_name:
                score += 10
            if target_address and target_address in org_address:
                score += 12
            for token in [token for token in target_address.split() if len(token) >= 2]:
                if token in org_name:
                    score += 2
                if token in org_address:
                    score += 3
            if score > best_score:
                best_score = score
                best_org = org

        if best_org:
            logger.info(
                "Stoplist public api organization resolved point=%s organization_id=%s address=%s score=%s",
                point.display_name,
                best_org.get("id"),
                best_org.get("address"),
                best_score,
            )
        return best_org

    async def _fetch_stoplist_products_via_public_api(self, point) -> list[str] | None:
        organization = await self._resolve_public_organization(point)
        if not organization or not organization.get("id"):
            return None

        categories = await self._fetch_public_json(
            f"https://italianpizza.ru/api/v3/organizations/{organization['id']}/categories"
        )
        if not isinstance(categories, list):
            return None

        items: list[str] = []
        for category in categories:
            for product in category.get("products") or []:
                status = str(product.get("status") or "").strip().lower()
                if status not in {"stop_list", "not_included_menu"}:
                    continue
                name = re.sub(r"\s+", " ", str(product.get("name") or "").replace("\xa0", " ")).strip()
                cleaned = self._clean_product_name(name)
                if cleaned and cleaned not in items:
                    items.append(cleaned)
        logger.info("Stoplist public api extracted point=%s products_found=%s", point.display_name, len(items))
        return items

    def _confirm_point_from_public_html(self, html: str, point, current_url: str) -> bool:
        normalized_html = self._normalize_text(html)
        normalized_city = self._normalize_text(point.city)
        normalized_address = self._normalize_text(point.address)
        street_tokens = [
            token
            for token in re.split(r"[\s,./-]+", normalized_address)
            if token and len(token) >= 2
        ]
        address_number_tokens = [token for token in street_tokens if any(ch.isdigit() for ch in token)]
        address_present = normalized_address in normalized_html or all(
            token in normalized_html for token in address_number_tokens[:2]
        )
        city_present = normalized_city in normalized_html
        url_matches = point.public_slug.lower() in (current_url or "").lower()
        confirmed = url_matches and city_present and address_present
        logger.info(
            "Stoplist public html confirm point=%s confirmed=%s url_matches=%s city_present=%s address_present=%s",
            point.display_name,
            confirmed,
            url_matches,
            city_present,
            address_present,
        )
        return confirmed

    def _extract_stoplist_products_from_html(self, html: str) -> list[str]:
        matches = re.finditer(r'"status":"stop_list".*?"name":"([^"]+)"', html, flags=re.DOTALL)
        results: list[str] = []
        for match in matches:
            raw_name = self._decode_json_string(match.group(1)).replace("\\/", "/")
            candidate = self._clean_product_name(raw_name)
            if candidate and candidate not in results:
                results.append(candidate)
        for candidate in self._extract_disabled_products_from_html(html):
            if candidate not in results:
                results.append(candidate)
        return results

    def _extract_disabled_products_from_html(self, html: str) -> list[str]:
        results: list[str] = []
        card_pattern = re.compile(
            r'<a href="/category/[^"]+/product/[^"]+"[^>]*>(.*?)</a>',
            flags=re.DOTALL | re.IGNORECASE,
        )
        for match in card_pattern.finditer(html):
            card_html = match.group(1)
            if "disabled" not in card_html.lower():
                continue

            title_match = re.search(r"<h[1-6][^>]*>(.*?)</h[1-6]>", card_html, flags=re.DOTALL | re.IGNORECASE)
            raw_name = ""
            if title_match:
                raw_name = re.sub(r"<[^>]+>", " ", title_match.group(1))
            else:
                alt_match = re.search(r'alt="([^"]+)"', card_html, flags=re.DOTALL | re.IGNORECASE)
                if alt_match:
                    raw_name = alt_match.group(1)

            candidate = self._clean_product_name(raw_name)
            if candidate and candidate not in results:
                results.append(candidate)
        return results

    def _page_excerpt(self, text: str, limit: int = 280) -> str:
        normalized = re.sub(r"\s+", " ", (text or "").strip())
        if len(normalized) <= limit:
            return normalized
        return normalized[: limit - 3].rstrip() + "..."

    def _detect_public_page_issue(self, text: str) -> str | None:
        lowered = re.sub(r"\s+", " ", (text or "").lower()).strip()
        if not lowered:
            return None
        if any(token in lowered for token in ["captcha", "капча", "я не робот", "i am not a robot"]):
            return "Публичный сайт запросил captcha."
        if any(token in lowered for token in ["нет доступа", "access denied", "403 forbidden", "forbidden", "ошибка 403", "код 403"]):
            return "Публичный сайт вернул отказ в доступе."
        if any(token in lowered for token in ["технические работы", "временно недоступен", "service unavailable", "ошибка 502", "ошибка 503", "ошибка 504", "код 502", "код 503", "код 504"]):
            return "Публичный сайт временно недоступен."
        return None

    def _build_failed_result(self, point_name: str, issue_text: str, diagnostics: dict | None = None) -> dict:
        report_text = f"Точка: {point_name}\nСтатус: {issue_text}"
        return {
            "status": "failed",
            "point_name": point_name,
            "selected": False,
            "report_text": report_text,
            "message": issue_text,
            "alert_hash": None,
            "diagnostics": diagnostics or {},
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
            if lowered in _ORDER_ACTION_LABELS:
                continue
            if re.fullmatch(r"[\d\s.,/-]+", line):
                continue
            if re.fullmatch(r"\d+[.,]?\d*\s*(г|кг|мл|л|см)\b", lowered):
                continue
            if any(marker in lowered for marker in ["₽", "руб", "доставка", "войти", "контакты", "заказать"]):
                continue
            if "***" in line or "скид" in lowered:
                continue
            if len(line.split()) > 10 or len(line) > 90:
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
                    await page.wait_for_timeout(700)
                    logger.info("Stoplist filled address input selector=%s index=%s value=%s", selector, idx, query)
                    suggestion_candidates = await self._collect_suggestion_candidates(page, query)
                    logger.info("Stoplist suggestion candidates=%s", suggestion_candidates)
                    if await self._click_suggestion(page, query):
                        await page.wait_for_timeout(800)
                        return True
                    await field.press("ArrowDown")
                    await page.wait_for_timeout(250)
                    await field.press("Enter")
                    await page.wait_for_timeout(800)
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
        for _ in range(5):
            try:
                await page.mouse.wheel(0, 2200)
            except Exception:
                await page.evaluate("window.scrollBy(0, 2200)")
            await page.wait_for_timeout(350)

    def _has_disabled_markers(self, text: str, disabled_attr: str | None, aria_disabled: str | None, classes: str) -> bool:
        lowered = re.sub(r"\s+", " ", (text or "").lower()).strip()
        normalized_classes = (classes or "").lower()
        if any(marker in lowered for marker in _DISABLED_TEXT_MARKERS):
            return True
        if disabled_attr is not None or aria_disabled == "true":
            return True
        if any(marker in normalized_classes for marker in _DISABLED_CLASS_MARKERS):
            return True
        return False

    async def _is_disabled_button(self, btn, action_text: str) -> bool:
        try:
            disabled_attr = await btn.get_attribute("disabled")
            aria_disabled = await btn.get_attribute("aria-disabled")
            classes = (await btn.get_attribute("class") or "").lower()
            if self._has_disabled_markers(action_text, disabled_attr, aria_disabled, classes):
                return True
            if not await btn.is_enabled():
                return True
        except Exception:
            return False
        return False

    async def _extract_card_title(self, card) -> str:
        title_selectors = [
            "h1", "h2", "h3", "h4",
            "[class*='title']", "[class*='Title']",
            "[class*='name']", "[class*='Name']",
            "[data-testid*='title']", "[data-testid*='name']",
            "strong", "b",
        ]
        for selector in title_selectors:
            locator = card.locator(selector)
            count = min(await locator.count(), 6)
            for idx in range(count):
                item = locator.nth(idx)
                try:
                    if not await item.is_visible():
                        continue
                    text = (await item.inner_text()).strip()
                except Exception:
                    continue
                candidate = self._clean_product_name(text)
                if candidate:
                    return candidate
        return ""

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
                card = locator.first
                title = await self._extract_card_title(card)
                if title:
                    return title
                text = (await card.inner_text()).strip()
                if text and len(text) > 2:
                    return text
            except Exception:
                continue
        return ""

    async def _collect_disabled_products(self, page) -> list[str]:
        results: list[str] = []
        locator = page.locator("button, [role='button']")
        count = min(await locator.count(), 140)
        for idx in range(count):
            btn = locator.nth(idx)
            try:
                if not await btn.is_visible():
                    continue
                text = re.sub(r"\s+", " ", (await btn.inner_text()).strip())
                if not self._looks_like_order_action(text):
                    continue
                if not await self._is_disabled_button(btn, text):
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
                "diagnostics": {"stage": "resolve_point"},
            }
        target_url = point.public_url.rstrip("/") + "/"
        stage = "public_api"
        try:
            api_items = await self._fetch_stoplist_products_via_public_api(point)
            if api_items is not None:
                if api_items:
                    report_text = "Точка: {}\nСтоп-лист:\n{}".format(
                        point.display_name,
                        "\n".join(f"- {item}" for item in api_items[:60]),
                    )
                else:
                    report_text = f"Точка: {point.display_name}\nСтоп-лист: недоступных позиций не найдено."
                return {
                    "status": "ok",
                    "point_name": point.display_name,
                    "selected": True,
                    "items": api_items,
                    "report_text": report_text,
                    "alert_hash": None,
                    "diagnostics": self._build_diagnostics(
                        stage,
                        target_url,
                        address_filled=True,
                        selected=True,
                        products_found=len(api_items),
                        source="public_api",
                    ),
                }
            logger.info("Stoplist public api returned no point-specific data point=%s, fallback to html", point.display_name)
        except (aiohttp.ClientError, TimeoutError) as exc:
            logger.warning("Stoplist public api failed point=%s error=%s", point.display_name, exc)
        except Exception as exc:
            logger.warning("Stoplist public api parse failed point=%s error=%s", point.display_name, exc, exc_info=True)

        stage = "fetch_html"
        try:
            logger.info("Stoplist public html fetch point=%s url=%s", point.display_name, target_url)
            html = await self._fetch_public_html(target_url)
            issue = self._detect_public_page_issue(html)
            if issue:
                return self._build_failed_result(
                    point.display_name,
                    issue,
                    diagnostics=self._build_diagnostics(stage, target_url),
                )

            stage = "point_confirm"
            if self._confirm_point_from_public_html(html, point, target_url):
                stage = "collect_products"
                cleaned = self._extract_stoplist_products_from_html(html)
                logger.info(
                    "Stoplist public html extracted point=%s products_found=%s",
                    point.display_name,
                    len(cleaned),
                )
                if cleaned:
                    report_text = "Точка: {}\nСтоп-лист:\n{}".format(
                        point.display_name,
                        "\n".join(f"- {item}" for item in cleaned[:60]),
                    )
                else:
                    report_text = f"Точка: {point.display_name}\nСтоп-лист: недоступных позиций не найдено."
                return {
                    "status": "ok",
                    "point_name": point.display_name,
                    "selected": True,
                    "items": cleaned,
                    "report_text": report_text,
                    "alert_hash": None,
                    "diagnostics": self._build_diagnostics(
                        stage,
                        target_url,
                        address_filled=True,
                        selected=True,
                        products_found=len(cleaned),
                        source="public_html",
                    ),
                }
            logger.info("Stoplist public html did not confirm point=%s, fallback to browser flow", point.display_name)
        except (aiohttp.ClientError, TimeoutError) as exc:
            logger.warning("Stoplist public html fetch failed point=%s error=%s", point.display_name, exc)
        except Exception as exc:
            logger.warning("Stoplist public html parse failed point=%s error=%s", point.display_name, exc, exc_info=True)
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError("Playwright is not installed") from exc

        stage = "launch"
        current_url = target_url
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context(locale="ru-RU", timezone_id="Europe/Moscow")
            page = await context.new_page()
            try:
                logger.info("Stoplist public browser run point=%s url=%s", point.display_name, target_url)
                stage = "goto"
                await page.goto(target_url, wait_until="domcontentloaded", timeout=25000)
                current_url = page.url
                await page.wait_for_timeout(1000)
                await self._dismiss_common_overlays(page)
                issue = self._detect_public_page_issue(await page.locator("body").inner_text())
                if issue:
                    return self._build_failed_result(
                        point.display_name,
                        issue,
                        diagnostics=self._build_diagnostics(stage, current_url),
                    )
                stage = "address_modal"
                await self._open_address_modal(page, point)
                stage = "delivery_mode"
                await self._set_delivery_mode(page)
                stage = "address_fill"
                address_filled = await self._fill_address(page, point)
                if not address_filled:
                    body = (await page.locator("body").inner_text())[:2000]
                    return self._build_failed_result(
                        point.display_name,
                        "Не удалось выбрать адрес на публичном сайте.",
                        diagnostics=self._build_diagnostics(
                            stage,
                            page.url,
                            address_filled=False,
                            selected=False,
                            products_found=0,
                            page_excerpt=self._page_excerpt(body),
                        ),
                    )
                stage = "confirm_point"
                selected = await self._confirm_selected_point(page, point)
                logger.info("Stoplist point selected=%s point=%s", selected, point.display_name)
                stage = "scroll"
                await self._scroll_all(page)
                await self._dismiss_common_overlays(page)
                selected = selected or await self._confirm_selected_point(page, point)
                stage = "collect_products"
                product_candidates = await self._collect_disabled_products(page)
                logger.info("Stoplist disabled button candidates point=%s items=%s", point.display_name, product_candidates[:60])
                cleaned: list[str] = []
                for item in product_candidates:
                    name = self._clean_product_name(item)
                    if name and name not in cleaned:
                        cleaned.append(name)
                if cleaned:
                    if not selected:
                        body = (await page.locator("body").inner_text())[:2000]
                        return self._build_failed_result(
                            point.display_name,
                            "Не удалось подтвердить выбор точки на публичном сайте.",
                            diagnostics=self._build_diagnostics(
                                stage,
                                page.url,
                                address_filled=address_filled,
                                selected=False,
                                products_found=len(cleaned),
                                page_excerpt=self._page_excerpt(body),
                            ),
                        )
                    report_text = "Точка: {}\nСтоп-лист:\n{}".format(
                        point.display_name,
                        "\n".join(f"- {item}" for item in cleaned[:60]),
                    )
                else:
                    body = (await page.locator("body").inner_text())[:2000]
                    issue = self._detect_public_page_issue(body)
                    if issue:
                        return self._build_failed_result(
                            point.display_name,
                            issue,
                            diagnostics=self._build_diagnostics(
                                stage,
                                page.url,
                                address_filled=address_filled,
                                selected=selected,
                                products_found=0,
                                page_excerpt=self._page_excerpt(body),
                            ),
                        )
                    if not selected:
                        return self._build_failed_result(
                            point.display_name,
                            "Не удалось подтвердить выбор точки на публичном сайте.",
                            diagnostics=self._build_diagnostics(
                                stage,
                                page.url,
                                address_filled=address_filled,
                                selected=False,
                                products_found=0,
                                page_excerpt=self._page_excerpt(body),
                            ),
                        )
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
                    "items": cleaned,
                    "report_text": report_text,
                    "alert_hash": None,
                    "diagnostics": self._build_diagnostics(
                        stage,
                        page.url,
                        address_filled=address_filled,
                        selected=selected,
                        products_found=len(cleaned),
                    ),
                }
            except Exception as exc:
                logger.error(
                    "Stoplist adapter failed point=%s stage=%s url=%s error=%s",
                    point.display_name,
                    stage,
                    current_url,
                    exc,
                    exc_info=True,
                )
                return self._build_failed_result(
                    point.display_name,
                    f"Техническая ошибка при проверке стоп-листа: {exc}",
                    diagnostics=self._build_diagnostics(stage, current_url),
                )
            finally:
                await context.close()
                await browser.close()


italian_pizza_public_adapter = ItalianPizzaPublicAdapter()
