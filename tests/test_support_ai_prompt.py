import os
import unittest

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("OPENAI_MODEL", "gpt-4o-mini")

from bot.support_ai import SUPPORT_SYSTEM_PROMPT


class SupportAIPromptTest(unittest.TestCase):
    def test_prompt_describes_current_agent_entry_points(self):
        self.assertIn("/agent", SUPPORT_SYSTEM_PROMPT)
        self.assertIn("обычным текстом", SUPPORT_SYSTEM_PROMPT)
        self.assertIn("покажи мониторинги", SUPPORT_SYSTEM_PROMPT)

    def test_prompt_no_longer_pushes_legacy_agent_guidance(self):
        self.assertNotIn("кнопку в /start", SUPPORT_SYSTEM_PROMPT)
        self.assertNotIn("Нажми /panel", SUPPORT_SYSTEM_PROMPT)
        self.assertNotIn("Попробуйте написать /start в группе", SUPPORT_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
