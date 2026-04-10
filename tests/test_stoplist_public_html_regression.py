import unittest

from data_agent.adapters.italian_pizza_public_adapter import ItalianPizzaPublicAdapter


class StoplistPublicHtmlRegressionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = ItalianPizzaPublicAdapter()

    def test_disabled_card_keeps_product_name_with_mushrooms(self):
        html = """
        <a href="/category/picca/product/rimskaya-slivochnaya-s-gribami">
          <article class="product-card disabled">
            <h3>Пицца Римская сливочная с грибами 30см</h3>
            <div>699 ₽</div>
            <div>490 г</div>
            <button disabled="">Выбрать</button>
          </article>
        </a>
        """
        self.assertEqual(
            self.adapter._extract_disabled_products_from_html(html),
            ["Пицца Римская сливочная с грибами 30см"],
        )

    def test_clean_product_name_filters_weight_line_but_not_mushroom_name(self):
        self.assertEqual(self.adapter._clean_product_name("490 г"), "")
        self.assertEqual(
            self.adapter._clean_product_name("Пицца Римская сливочная с грибами 30см"),
            "Пицца Римская сливочная с грибами 30см",
        )


if __name__ == "__main__":
    unittest.main()
