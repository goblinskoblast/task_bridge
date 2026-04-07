import asyncio
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace

from webhook_lifecycle import build_webhook_lifespan


class _FakeLogger:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def info(self, message: str, *args) -> None:
        self.messages.append(message % args if args else message)


class _FakeBot:
    def __init__(self) -> None:
        self.webhook_calls: list[tuple[str, list[str]]] = []

    async def set_webhook(self, target: str, allowed_updates: list[str]) -> None:
        self.webhook_calls.append((target, allowed_updates))


class _FakeDispatcher:
    def resolve_used_update_types(self) -> list[str]:
        return ["message", "callback_query"]


class _FakeApp:
    def __init__(self, events: list[str]) -> None:
        @asynccontextmanager
        async def original_lifespan(_: object):
            events.append("original_enter")
            try:
                yield
            finally:
                events.append("original_exit")

        self.router = SimpleNamespace(lifespan_context=original_lifespan)
        self.state = SimpleNamespace(taskbridge_bot=None, taskbridge_dispatcher=None)


class WebhookLifespanTest(unittest.TestCase):
    def test_webhook_lifespan_initializes_and_closes_runtime(self) -> None:
        events: list[str] = []
        logger = _FakeLogger()
        app = _FakeApp(events)
        bot = _FakeBot()
        dispatcher = _FakeDispatcher()
        scheduler_calls: list[_FakeBot] = []
        closed_bots: list[_FakeBot] = []

        async def initialize_runtime():
            events.append("initialize")
            return bot, dispatcher

        async def close_runtime(current_bot):
            events.append("close")
            closed_bots.append(current_bot)

        def start_scheduler(current_bot):
            events.append("scheduler")
            scheduler_calls.append(current_bot)

        lifespan = build_webhook_lifespan(
            app=app,
            use_webhook=True,
            webhook_url="https://web-production.up.railway.app",
            webhook_target="https://web-production.up.railway.app/webhook",
            initialize_runtime=initialize_runtime,
            close_runtime=close_runtime,
            start_scheduler=start_scheduler,
            logger=logger,
        )

        async def run_test() -> None:
            async with lifespan(app):
                self.assertIs(app.state.taskbridge_bot, bot)
                self.assertIs(app.state.taskbridge_dispatcher, dispatcher)

        asyncio.run(run_test())

        self.assertEqual(events, ["original_enter", "initialize", "scheduler", "close", "original_exit"])
        self.assertEqual(
            bot.webhook_calls,
            [("https://web-production.up.railway.app/webhook", ["message", "callback_query"])],
        )
        self.assertEqual(scheduler_calls, [bot])
        self.assertEqual(closed_bots, [bot])
        self.assertIsNone(app.state.taskbridge_bot)
        self.assertIsNone(app.state.taskbridge_dispatcher)
        self.assertIn("Webhook set to https://web-production.up.railway.app/webhook", logger.messages)

    def test_webhook_lifespan_skips_runtime_when_disabled(self) -> None:
        events: list[str] = []
        logger = _FakeLogger()
        app = _FakeApp(events)

        async def initialize_runtime():
            raise AssertionError("initialize_runtime should not be called")

        async def close_runtime(current_bot):
            raise AssertionError("close_runtime should not be called")

        def start_scheduler(current_bot):
            raise AssertionError("start_scheduler should not be called")

        lifespan = build_webhook_lifespan(
            app=app,
            use_webhook=False,
            webhook_url="https://web-production.up.railway.app",
            webhook_target="https://web-production.up.railway.app/webhook",
            initialize_runtime=initialize_runtime,
            close_runtime=close_runtime,
            start_scheduler=start_scheduler,
            logger=logger,
        )

        async def run_test() -> None:
            async with lifespan(app):
                self.assertIsNone(app.state.taskbridge_bot)
                self.assertIsNone(app.state.taskbridge_dispatcher)

        asyncio.run(run_test())
        self.assertEqual(events, ["original_enter", "original_exit"])

    def test_webhook_lifespan_requires_real_url(self) -> None:
        events: list[str] = []
        logger = _FakeLogger()
        app = _FakeApp(events)

        async def initialize_runtime():
            raise AssertionError("initialize_runtime should not be called")

        async def close_runtime(current_bot):
            raise AssertionError("close_runtime should not be called")

        def start_scheduler(current_bot):
            raise AssertionError("start_scheduler should not be called")

        lifespan = build_webhook_lifespan(
            app=app,
            use_webhook=True,
            webhook_url="https://your-domain.com",
            webhook_target="https://your-domain.com/webhook",
            initialize_runtime=initialize_runtime,
            close_runtime=close_runtime,
            start_scheduler=start_scheduler,
            logger=logger,
        )

        async def run_test() -> None:
            async with lifespan(app):
                pass

        with self.assertRaisesRegex(RuntimeError, "WEBHOOK_URL must be configured"):
            asyncio.run(run_test())

        self.assertEqual(events, ["original_enter", "original_exit"])


if __name__ == "__main__":
    unittest.main()
