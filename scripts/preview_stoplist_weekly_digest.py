from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_agent.stoplist_digest_scheduler import build_stoplist_weekly_digest_preview


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preview weekly stoplist digest delivery for a specific Telegram user."
    )
    parser.add_argument("--telegram-user-id", type=int, default=137236883)
    parser.add_argument("--lookback-days", type=int, default=7)
    args = parser.parse_args()

    payload = build_stoplist_weekly_digest_preview(
        telegram_user_id=args.telegram_user_id,
        lookback_days=args.lookback_days,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
