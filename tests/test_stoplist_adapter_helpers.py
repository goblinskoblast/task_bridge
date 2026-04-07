import unittest

from data_agent.adapters.italian_pizza_public_adapter import ItalianPizzaPublicAdapter


class StoplistAdapterHelpersTest(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = ItalianPizzaPublicAdapter()

    def test_detect_public_page_issue(self):
        self.assertEqual(
            self.adapter._detect_public_page_issue("403 forbidden"),
            "Публичный сайт вернул отказ в доступе.",
        )
        self.assertEqual(
            self.adapter._detect_public_page_issue("Идут технические работы"),
            "Публичный сайт временно недоступен.",
        )

    def test_looks_like_order_action(self):
        self.assertTrue(self.adapter._looks_like_order_action("Выбрать"))
        self.assertTrue(self.adapter._looks_like_order_action("Добавить в корзину"))
        self.assertFalse(self.adapter._looks_like_order_action("Подробнее"))

    def test_build_failed_result(self):
        result = self.adapter._build_failed_result(
            "Екатеринбург, Сулимова 31А",
            "Публичный сайт временно недоступен.",
            diagnostics={"stage": "goto", "selected": False, "products_found": 0},
        )
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["selected"])
        self.assertIn("временно недоступен", result["report_text"])
        self.assertEqual(result["diagnostics"]["stage"], "goto")
        self.assertEqual(result["diagnostics"]["products_found"], 0)


if __name__ == "__main__":
    unittest.main()
