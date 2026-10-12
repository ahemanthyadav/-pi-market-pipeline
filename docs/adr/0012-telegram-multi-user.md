# 0012. Telegram bot becomes multi-user: owner + `bot_users`, everyone has their own setup

- Date: 2026-10-12
- Status: accepted (deployed — `telegram-digest:v8` and schema `09-multiuser.sql` live 2026-10-12)
- Supersedes the "single-user allow-list" security model of ADR 0009 (the delivery design there is unchanged).

## Context
ADR 0009 made the Telegram bot single-user by design: one `TELEGRAM_CHAT_ID`, everyone else logged and ignored, one
global `watchlist`. A second person wanted access. Three things made "just add their id" wrong: replies and the
digest/alert sends were hard-wired to that one chat; the `watchlist` holds quantities and average cost (a portfolio) and
was keyed by symbol only, so a second user would have read and edited the owner's holdings; and a short-lived workaround
(pointing the Secret at a Telegram *group*) showed the cost — every member of the group saw every reply, `/watch`
included. The requirement became: **every user has their own setup**.

## Decision
1. **Owner + members.** The owner is whoever the Secret's `chat-id` names; always allowed, the only one who can manage
   users, and **not** a row in the table (so a Secret change can never lock the owner out or leave two owners). Members
   are the active rows of the new `bot_users` table (`chat_id`, `name`, `active`, `added_at`, `added_by`).
2. **Access is data, not config.** The owner manages members from their own chat — `/adduser <chat_id> [name]`,
   `/rmuser <chat_id>`, `/users` — so adding a person needs no Secret edit, no restart and no deploy. Cached 30 s in the
   bot, invalidated on every change. A removed member is deactivated, not deleted: their watchlist is kept and
   `/adduser` restores it.
3. **Per-user state.** `watchlist` is keyed `(chat_id, symbol)`; `/watch`, the digest's watchlist section and the
   watchlist alerts are all scoped by one SQL parameter (`WATCH_SQL … WHERE w.chat_id = %s`). Market data (indices,
   screener, FX, news) stays shared and read-only. Replies go to the chat that asked.
4. **Scheduled sends fan out per user.** `digest.py` and `alerts.py` build one message per recipient (shared market part +
   that user's own watchlist) via `users.deliver()`. One member's failure (e.g. they blocked the bot) is logged as a WARN and
   never blocks the others or fails the Job; the Job fails only if the **owner's** send fails or every send fails.
5. **Unknown chats are still never answered** (the bot is public). New: the owner gets **one** notice per unknown chat
   per 24 h (and at most 10 an hour overall) containing a ready-to-send `/adduser <id> Name` line — so the id never has to be
   dug out of a log. The stranger gets nothing, so the bot's existence is not confirmed to them.
6. **Degrades safely.** If `bot_users` does not exist (schema 09 not applied) or the DB blips, the registry falls back to
   "owner only" / the last known member list; the owner can never be locked out. A missing watchlist column is treated like
   a missing table (`UndefinedColumn`), so a new image on an old schema, or the reverse, degrades instead of crashing.
7. **Groups are allowed but are a *shared* setup**: a negative chat id can be added as a member and then shares one
   watchlist among everyone in it. Recommended: each person uses a private chat with the bot.

## Consequences
- **Good:** no Secret edits or restarts to add someone; holdings are private per chat; the owner learns who is knocking and
  can approve in one message; fully unit-tested (`tests/test_multiuser.py`, 38 tests incl. mutation-checked allow-list and
  watchlist scoping) and the real deployed code was exercised live against the DB with a throwaway member.
- **Not private from the operator:** the database superuser (every job uses it — review AR-8) can read every watchlist.
  There is deliberately no bot command that shows another user's holdings, and `/users` shows only symbol *counts*.
- **Shared limits:** all users share the schedule (08:00 IST digest), the 5 % alert threshold and the 4096-char limit; per-user
  schedules/thresholds are a later extension. `MAX_MEMBERS = 20`.
- **Needs a user action:** a new member must send `/start` to the bot once before Telegram lets the bot message them.
- **Migration:** `09-multiuser.sql` is idempotent and **refuses to guess an owner** if `watchlist` has rows without a
  `chat_id` (it was empty when applied). Rollback: `/rmuser` everyone, then the old shape is
  `ALTER TABLE watchlist DROP CONSTRAINT watchlist_pkey, DROP COLUMN chat_id, ADD PRIMARY KEY (symbol)` (only valid while
  no two users watch the same symbol) — and redeploy `telegram-digest:v7`.
- **Operational note:** the permission config denies deleting anything named `timescaledb…`, so the schema Job could not be
  deleted and re-created under its own name; it was re-run as `schema-multiuser-09` (same manifest, new name).
