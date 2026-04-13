import unittest

from data_agent.adapters.italian_pizza_public_adapter import ItalianPizzaPublicAdapter
from data_agent.italian_pizza import resolve_italian_pizza_point


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

    def test_has_disabled_markers(self):
        self.assertTrue(self.adapter._has_disabled_markers("Недоступно", None, None, ""))
        self.assertTrue(self.adapter._has_disabled_markers("Выбрать", None, "true", ""))
        self.assertTrue(self.adapter._has_disabled_markers("В корзину", None, None, "product-card is-disabled"))
        self.assertFalse(self.adapter._has_disabled_markers("Выбрать", None, None, "product-card"))

    def test_clean_product_name_filters_prices_and_actions(self):
        self.assertEqual(self.adapter._clean_product_name("1199"), "")
        self.assertEqual(self.adapter._clean_product_name("Выбрать"), "")
        self.assertEqual(
            self.adapter._clean_product_name("Луковые кольца малая порция"),
            "Луковые кольца малая порция",
        )

    def test_build_failed_result(self):
        result = self.adapter._build_failed_result(
            "Екатеринбург, Сулимова 31А",
            "Публичный сайт временно недоступен.",
            diagnostics={"stage": "goto", "selected": False, "products_found": 0},
        )
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["selected"])
        self.assertEqual(result["report_text"], "Не удалось получить отчет по стоп-листу. Попробуйте позже.")
        self.assertEqual(result["diagnostics"]["issue_text"], "Публичный сайт временно недоступен.")
        self.assertEqual(result["diagnostics"]["stage"], "goto")
        self.assertEqual(result["diagnostics"]["products_found"], 0)

    def test_confirm_point_from_public_html_uses_city_address_and_slug(self):
        point = resolve_italian_pizza_point("Верхний Уфалей, Ленина 147")
        html = """
        <html>
          <head>
            <title>Доставка пиццы Верхний Уфалей</title>
            <meta itemprop="streetAddress" content="г. Верхний Уфалей ул. Ленина, д. 147" />
          </head>
        </html>
        """
        self.assertTrue(self.adapter._confirm_point_from_public_html(html, point, "https://ufaley.italianpizza.ru/"))
        self.assertFalse(self.adapter._confirm_point_from_public_html(html, point, "https://ekb.italianpizza.ru/"))

    def test_extract_stoplist_products_from_html(self):
        html = """
        {"status":"free","name":"Маргарита"}
        {"status":"stop_list","id":"1","name":"Римские каникулы"}
        {"status":"stop_list","id":"2","name":"Авторский чай: Мохито 300 мл"}
        """
        self.assertEqual(
            self.adapter._extract_stoplist_products_from_html(html),
            ["Римские каникулы", "Авторский чай: Мохито 300 мл"],
        )


    def test_resolve_sukhoy_log_uses_current_public_slug(self):
        point = resolve_italian_pizza_point("Сухой Лог, Белинского 40")
        self.assertIsNotNone(point)
        self.assertEqual(point.public_slug, "suxoj-log")
        self.assertEqual(point.public_url, "https://suxoj-log.italianpizza.ru")


if __name__ == "__main__":
    unittest.main()
