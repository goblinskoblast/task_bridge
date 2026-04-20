import os
import unittest

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from main import set_bot_commands as set_webhook_bot_commands
from main_bot_only import set_bot_commands as set_polling_bot_commands


class DummyBot:
    def __init__(self) -> None:
        self.deleted_scopes = []

    async def delete_my_commands(self, *, scope=None, language_code=None) -> None:
        self.deleted_scopes.append((scope, language_code))

    async def set_my_commands(self, *args, **kwargs) -> None:
        raise AssertionError("Slash-command menu should stay hidden")


class BotCommandMenuTest(unittest.IsolatedAsyncioTestCase):
    async def test_webhook_runtime_clears_slash_command_menu(self):
        bot = DummyBot()

        await set_webhook_bot_commands(bot)

        self.assertEqual(len(bot.deleted_scopes), 1)
        self.assertIsNotNone(bot.deleted_scopes[0][0])

    async def test_polling_runtime_clears_slash_command_menu(self):
        bot = DummyBot()

        await set_polling_bot_commands(bot)

        self.assertEqual(len(bot.deleted_scopes), 1)
        self.assertIsNotNone(bot.deleted_scopes[0][0])
