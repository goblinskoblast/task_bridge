import unittest

from data_agent.system_catalog import (
    capability_labels,
    detect_system_name_from_url,
    is_italian_pizza_descriptor,
    normalize_system_name,
    orientation_summary,
    resolve_system_descriptor,
)


class SystemCatalogTest(unittest.TestCase):
    def test_detect_system_name_from_italian_pizza_url(self):
        self.assertEqual(
            detect_system_name_from_url("https://tochka.italianpizza.ru/login"),
            "italian_pizza",
        )

    def test_detect_system_name_from_iiko_url(self):
        self.assertEqual(
            detect_system_name_from_url("https://sso.iiko.biz/auth"),
            "iiko",
        )

    def test_detect_system_name_from_keeper_url(self):
        self.assertEqual(
            detect_system_name_from_url("https://cloud.rkeeper.com/dashboard"),
            "keeper",
        )

    def test_normalize_system_name_supports_legacy_aliases(self):
        self.assertEqual(normalize_system_name("crm"), "CRM")
        self.assertEqual(normalize_system_name("web_system"), "web-system")
        self.assertEqual(normalize_system_name("1c"), "1C")

    def test_resolve_system_descriptor_prefers_detected_url_over_generic_name(self):
        descriptor = resolve_system_descriptor(
            system_name="web-system",
            url="https://tochka.italianpizza.ru/login",
        )

        self.assertEqual(descriptor.system_name, "italian_pizza")
        self.assertTrue(descriptor.supports_scan)
        self.assertTrue(descriptor.supports_points)
        self.assertTrue(descriptor.supports_monitoring)

    def test_resolve_system_descriptor_for_max_channel(self):
        descriptor = resolve_system_descriptor(system_name="max")

        self.assertEqual(descriptor.system_name, "max")
        self.assertEqual(descriptor.family, "messenger_channel")
        self.assertTrue(descriptor.supports_chat_delivery)

    def test_capability_labels_and_orientation_summary_for_iiko(self):
        descriptor = resolve_system_descriptor(system_name="iiko")

        self.assertIn("scan", capability_labels(descriptor))
        self.assertIn("мониторинг", capability_labels(descriptor))
        self.assertIn("организация", orientation_summary(descriptor))

    def test_is_italian_pizza_descriptor(self):
        self.assertTrue(is_italian_pizza_descriptor(system_name="italian_pizza"))
        self.assertTrue(is_italian_pizza_descriptor(url="https://tochka.italianpizza.ru/login"))
        self.assertFalse(is_italian_pizza_descriptor(system_name="iiko"))


if __name__ == "__main__":
    unittest.main()
