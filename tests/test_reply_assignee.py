import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from bot.handlers import _extract_reply_assignee_hint, _resolve_assignee_usernames


class ReplyAssigneeTest(unittest.TestCase):
    def _build_message(self, *, sender_id: int = 10, reply_user: SimpleNamespace | None = None):
        return SimpleNamespace(
            from_user=SimpleNamespace(id=sender_id, username="author", first_name="Author", is_bot=False),
            reply_to_message=SimpleNamespace(from_user=reply_user) if reply_user else None,
        )

    def test_reply_target_with_username_becomes_assignee_hint(self):
        message = self._build_message(
            reply_user=SimpleNamespace(
                id=42,
                username="vladislav",
                first_name="Владислав",
                last_name=None,
                is_bot=False,
            )
        )

        hint = _extract_reply_assignee_hint(message)

        self.assertIsNotNone(hint)
        self.assertEqual(hint["token"], "vladislav")

    def test_reply_target_without_username_falls_back_to_tgid_token(self):
        message = self._build_message(
            reply_user=SimpleNamespace(
                id=77,
                username=None,
                first_name="Владислав",
                last_name=None,
                is_bot=False,
            )
        )

        hint = _extract_reply_assignee_hint(message)

        self.assertIsNotNone(hint)
        self.assertEqual(hint["token"], "tgid:77")

    def test_reply_to_self_is_ignored(self):
        message = self._build_message(
            sender_id=55,
            reply_user=SimpleNamespace(
                id=55,
                username="same_user",
                first_name="Self",
                last_name=None,
                is_bot=False,
            )
        )

        self.assertIsNone(_extract_reply_assignee_hint(message))

    def test_reply_hint_used_only_when_ai_found_no_assignee(self):
        reply_hint = {"token": "vladislav"}

        self.assertEqual(
            _resolve_assignee_usernames({"assignee_usernames": []}, reply_assignee_hint=reply_hint),
            ["vladislav"],
        )
        self.assertEqual(
            _resolve_assignee_usernames({"assignee_usernames": ["analyst"]}, reply_assignee_hint=reply_hint),
            ["analyst"],
        )


if __name__ == "__main__":
    unittest.main()
