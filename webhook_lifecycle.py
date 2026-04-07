from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Awaitable, Callable


InitializeRuntime = Callable[[], Awaitable[tuple[Any, Any]]]
CloseRuntime = Callable[[Any], Awaitable[None]]
StartScheduler = Callable[[Any], None]


def build_webhook_lifespan(
    *,
    app: Any,
    use_webhook: bool,
    webhook_url: str,
    webhook_target: str,
    initialize_runtime: InitializeRuntime,
    close_runtime: CloseRuntime,
    start_scheduler: StartScheduler,
    logger: Any,
) -> Callable[[Any], AsyncIterator[None]]:
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def webhook_lifespan(inner_app: Any) -> AsyncIterator[None]:
        async with original_lifespan(inner_app):
            if not use_webhook:
                yield
                return

            if not webhook_url or "your-domain.com" in webhook_url:
                raise RuntimeError("WEBHOOK_URL must be configured for webhook mode")

            bot, dispatcher = await initialize_runtime()
            inner_app.state.taskbridge_bot = bot
            inner_app.state.taskbridge_dispatcher = dispatcher

            await bot.set_webhook(
                webhook_target,
                allowed_updates=dispatcher.resolve_used_update_types(),
            )
            logger.info("Webhook set to %s", webhook_target)

            start_scheduler(bot)
            logger.info("Reminder scheduler started")

            try:
                yield
            finally:
                current_bot = getattr(inner_app.state, "taskbridge_bot", None)
                try:
                    await close_runtime(current_bot)
                finally:
                    inner_app.state.taskbridge_bot = None
                    inner_app.state.taskbridge_dispatcher = None

    return webhook_lifespan
