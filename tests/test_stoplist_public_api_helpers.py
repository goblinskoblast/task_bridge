import unittest

from data_agent.adapters.italian_pizza_public_adapter import ItalianPizzaPublicAdapter


class StoplistPublicApiHelpersTest(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_stoplist_products_via_public_api_filters_only_stop_list(self):
        adapter = ItalianPizzaPublicAdapter()

        async def fake_resolve(point):
            return {"id": "org-1"}

        async def fake_fetch(url, *, params=None):
            self.assertEqual(url, "https://italianpizza.ru/api/v3/organizations/org-1/categories")
            return [
                {
                    "name": "Pizza",
                    "products": [
                        {"status": "free", "name": "Fitness Box"},
                        {"status": "stop_list", "name": "Roman Mushroom 30"},
                        {"status": "not_included_menu", "name": "Snake Candy"},
                    ],
                },
                {
                    "name": "Drinks",
                    "products": [
                        {"status": "stop_list", "name": "Mint Tea 300"},
                        {"status": "free", "name": "Fruit Popcorn"},
                    ],
                },
            ]

        adapter._resolve_public_organization = fake_resolve  # type: ignore[method-assign]
        adapter._fetch_public_json = fake_fetch  # type: ignore[method-assign]

        point = type("Point", (), {"display_name": "Test", "address": "Test 1"})()
        items = await adapter._fetch_stoplist_products_via_public_api(point)

        self.assertEqual(items, ["Roman Mushroom 30", "Mint Tea 300"])

    async def test_reconcile_stoplist_products_drops_api_only_items(self):
        adapter = ItalianPizzaPublicAdapter()

        api_items = ["Roman Mushroom 30", "Quesadilla", "Mint Tea 300"]
        html_items = ["Roman Mushroom 30", "Mint Tea 300", "Fruit Popcorn"]

        self.assertEqual(
            adapter._reconcile_stoplist_products(api_items, html_items),
            ["Roman Mushroom 30", "Mint Tea 300"],
        )

    async def test_reconcile_stoplist_products_keeps_api_when_no_overlap(self):
        adapter = ItalianPizzaPublicAdapter()

        api_items = ["Roman Mushroom 30", "Mint Tea 300"]
        html_items = ["Fruit Popcorn", "Fitness Box"]

        self.assertEqual(
            adapter._reconcile_stoplist_products(api_items, html_items),
            api_items,
        )


if __name__ == "__main__":
    unittest.main()
