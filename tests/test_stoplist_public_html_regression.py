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


    def test_clean_product_name_appends_size_when_it_is_on_separate_line(self):
        self.assertEqual(
            self.adapter._clean_product_name("Пицца Пепперони\n30 см\n699 ₽\n490 г"),
            "Пицца Пепперони 30 см",
        )

    def test_extract_disabled_products_from_html_keeps_separate_size_variants(self):
        html = """
        <a href="/category/picca/product/pepperoni-30">
          <article class="product-card disabled">
            <h3>Пицца Пепперони</h3>
            <div>30 см</div>
            <div>699 ₽</div>
            <button disabled="">Выбрать</button>
          </article>
        </a>
        <a href="/category/picca/product/pepperoni-40">
          <article class="product-card disabled">
            <h3>Пицца Пепперони</h3>
            <div>40 см</div>
            <div>999 ₽</div>
            <button disabled="">Выбрать</button>
          </article>
        </a>
        """
        self.assertEqual(
            self.adapter._extract_disabled_products_from_html(html),
            ["Пицца Пепперони 30 см", "Пицца Пепперони 40 см"],
        )


if __name__ == "__main__":
    unittest.main()
