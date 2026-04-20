import asyncio
import os
import unittest
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from bot.handlers import (
    _extract_observed_message_metadata,
    _extract_reply_assignee_hint,
    _resolve_assignee_usernames,
    get_or_create_user_by_username,
)
from db.models import User


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
                first_name="?????????",
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
                first_name="?????????",
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

    def test_get_or_create_user_by_username_allocates_unique_placeholder_ids(self):
        engine = create_engine("sqlite:///:memory:")
        User.__table__.create(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        try:
            db.add(User(telegram_id=-1, username="existing", first_name="@existing", is_bot=False))
            db.commit()

            created = asyncio.run(get_or_create_user_by_username(db, "newuser"))

            self.assertEqual(created.username, "newuser")
            self.assertEqual(created.telegram_id, -2)
        finally:
            db.close()

    def test_get_or_create_user_by_username_reuses_existing_username(self):
        engine = create_engine("sqlite:///:memory:")
        User.__table__.create(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        try:
            existing = User(telegram_id=-5, username="dr.cyrill", first_name="@dr.cyrill", is_bot=False)
            db.add(existing)
            db.commit()

            resolved = asyncio.run(get_or_create_user_by_username(db, "dr.cyrill"))

            self.assertEqual(resolved.id, existing.id)
            self.assertEqual(resolved.telegram_id, -5)
        finally:
            db.close()

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

    def test_observed_message_metadata_tracks_reply_to_bot(self):
        message = SimpleNamespace(
            reply_to_message=SimpleNamespace(
                message_id=9001,
                from_user=SimpleNamespace(is_bot=True),
            ),
            forward_origin=None,
            forward_from=None,
            forward_from_chat=None,
            forward_date=None,
        )

        metadata = _extract_observed_message_metadata(message)

        self.assertEqual(metadata["reply_to_message_id"], 9001)
        self.assertTrue(metadata["reply_to_from_bot"])
        self.assertFalse(metadata["is_forwarded"])

    def test_observed_message_metadata_tracks_forward_origin(self):
        message = SimpleNamespace(
            reply_to_message=None,
            forward_origin=SimpleNamespace(
                type="user",
                sender_user=SimpleNamespace(
                    username="taskbridge_bot",
                    first_name="TaskBridge",
                    last_name=None,
                    is_bot=True,
                ),
            ),
            forward_from=None,
            forward_from_chat=None,
            forward_date=None,
        )

        metadata = _extract_observed_message_metadata(message)

        self.assertTrue(metadata["is_forwarded"])
        self.assertEqual(metadata["forward_origin_type"], "user")
        self.assertEqual(metadata["forward_origin_title"], "@taskbridge_bot")
        self.assertTrue(metadata["forward_from_bot"])


if __name__ == "__main__":
    unittest.main()
