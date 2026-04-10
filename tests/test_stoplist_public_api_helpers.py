import unittest

from data_agent.adapters.italian_pizza_public_adapter import ItalianPizzaPublicAdapter


class StoplistPublicApiHelpersTest(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_stoplist_products_via_public_api_filters_only_stop_statuses(self):
        adapter = ItalianPizzaPublicAdapter()

        async def fake_resolve(point):
            return {"id": "org-1"}

        async def fake_fetch(url, *, params=None):
            self.assertEqual(url, "https://italianpizza.ru/api/v3/organizations/org-1/categories")
            return [
                {
                    "name": "Пицца",
                    "products": [
                        {"status": "free", "name": "Фэтнесс бокс"},
                        {"status": "stop_list", "name": "Пицца Римская сливочная с грибами 30см"},
                        {"status": "not_included_menu", "name": "КрутФрут Змейка"},
                    ],
                },
                {
                    "name": "Напитки",
                    "products": [
                        {"status": "stop_list", "name": "Авторский чай: Мохито 300 мл"},
                        {"status": "free", "name": "Попкорн Фруктовый микс 90 гр"},
                    ],
                },
            ]

        adapter._resolve_public_organization = fake_resolve  # type: ignore[method-assign]
        adapter._fetch_public_json = fake_fetch  # type: ignore[method-assign]

        point = type("Point", (), {"display_name": "Тест", "address": "Тест 1"})()
        items = await adapter._fetch_stoplist_products_via_public_api(point)

        self.assertEqual(
            items,
            [
                "Пицца Римская сливочная с грибами 30см",
                "КрутФрут Змейка",
                "Авторский чай: Мохито 300 мл",
            ],
        )


if __name__ == "__main__":
    unittest.main()
