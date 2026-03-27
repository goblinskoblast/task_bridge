# Demo Reviews Scenario

This document describes the first vertical DataAgent scenario for restaurant operations.

## Goal

Build a reviews report from a configured Google Sheets or CSV source and deliver it through Telegram.

## Current flow

1. Configure `REVIEWS_SHEET_URL` with a Google Sheets link or direct CSV export URL.
2. User sends `/reviews` or `/reviews month` in Telegram.
3. TaskBridge forwards the request to `data_agent`.
4. `data_agent` selects `review_tool`.
5. `review_tool`:
   - downloads CSV
   - filters rows by period
   - aggregates review sentiment
   - groups issues by service, delivery, kitchen, and other
6. Orchestrator returns a concise Russian report.

## Supported periods

- current week
- current month
- explicit date range in the user request via the tool API

## Required CSV fields

The parser is flexible, but best results come when the source contains these columns:

- review text or comment
- review date
- rating
- branch or location

## Expected next steps

- add branch-level drill-down
- add export to mini app
- add scheduled reviews digest
- add Pinpong/browser source as a second reviews provider
