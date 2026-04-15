from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db.database import get_db_session
from db.models import DataAgentMonitorConfig, User
from data_agent.monitor_scheduler import _run_blanks_monitor, _run_reviews_monitor, _run_stoplist_monitor


class _ProbeBot:
    async def send_message(self, **kwargs) -> None:
        raise RuntimeError("probe mode must not send Telegram messages")


async def _run_probe(telegram_user_id: int, monitor_type: str | None, point_name: str | None) -> list[dict]:
    db = get_db_session()
    try:
        user = db.query(User).filter(User.telegram_id == telegram_user_id).first()
        if not user:
            raise RuntimeError(f"user with telegram_id={telegram_user_id} not found")

        query = db.query(DataAgentMonitorConfig).filter(
            DataAgentMonitorConfig.user_id == user.id,
            DataAgentMonitorConfig.is_active == True,
        )
        if monitor_type:
            query = query.filter(DataAgentMonitorConfig.monitor_type == monitor_type)
        if point_name:
            query = query.filter(DataAgentMonitorConfig.point_name == point_name)
        configs = query.order_by(DataAgentMonitorConfig.monitor_type.asc(), DataAgentMonitorConfig.point_name.asc()).all()

        bot = _ProbeBot()
        results: list[dict] = []
        for config in configs:
            if config.monitor_type == "blanks":
                result = await _run_blanks_monitor(bot, config, notify_user=False, persist_state=False)
            elif config.monitor_type == "stoplist":
                result = await _run_stoplist_monitor(bot, config, notify_user=False, persist_state=False)
            elif config.monitor_type == "reviews":
                result = await _run_reviews_monitor(bot, config, notify_user=False, persist_state=False)
            else:
                result = {"status": "unsupported_monitor_type", "monitor_type": config.monitor_type}

            results.append(
                {
                    "config_id": config.id,
                    "user_id": config.user_id,
                    "monitor_type": config.monitor_type,
                    "point_name": config.point_name,
                    "result": result,
                }
            )
        return results
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Safe monitor probe without DB writes or Telegram delivery.")
    parser.add_argument("--telegram-user-id", type=int, required=True)
    parser.add_argument("--monitor-type", choices=["blanks", "stoplist", "reviews"])
    parser.add_argument("--point-name")
    args = parser.parse_args()

    results = asyncio.run(_run_probe(args.telegram_user_id, args.monitor_type, args.point_name))
    print(json.dumps(results, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
