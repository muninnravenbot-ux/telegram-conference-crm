"""Data sources for the conference CRM.

Each source returns a list of "chat aggregate" dicts, already filtered to the
conference window and the group-size limit:

    {
      "name": str,                # display name / chat title
      "username": str,            # "@handle" or "" if none
      "user_id": int | "",        # Telegram numeric id (great for deep links)
      "is_group": bool,
      "group_size": int,          # distinct participants (groups only)
      "members": list[str],       # other members' "@handle"/name (groups only)
      "msgs_in_window": int,
      "their_replies": int,       # window messages NOT sent by you
      "first_ever": date,         # oldest message ever in this chat
      "last_before": date | None, # newest message before the window (None = none)
    }

Two sources:
  * parse_export()  — offline, reads a Telegram Desktop JSON export. Gives names
    and numeric ids (from `from_id`), but Telegram exports do not include
    @usernames, so `username` is blank.
  * gather_live()   — online, uses Telethon with the user's own API credentials.
    Gives names, numeric ids AND @usernames. Read-only.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import date, datetime

PERSONAL_TYPES = {"personal_chat", "saved_messages"}
GROUP_TYPES = {"private_group", "private_supergroup", "public_supergroup",
               "public_channel", "bot_chat"}

_ID_RE = re.compile(r"(\d+)")


def _num_id(from_id) -> int | str:
    if from_id is None:
        return ""
    m = _ID_RE.search(str(from_id))
    return int(m.group(1)) if m else ""


def _msg_date(msg: dict) -> date | None:
    ux = msg.get("date_unixtime")
    if ux is not None:
        try:
            return datetime.fromtimestamp(int(ux)).date()
        except (ValueError, OSError):
            pass
    raw = msg.get("date")
    if raw:
        try:
            return datetime.fromisoformat(raw).date()
        except ValueError:
            return None
    return None


def _msg_text(msg: dict) -> str:
    """Telegram 'text' can be a plain string or a list of text-entity parts."""
    t = msg.get("text")
    if isinstance(t, str):
        return t
    if isinstance(t, list):
        parts = []
        for x in t:
            if isinstance(x, str):
                parts.append(x)
            elif isinstance(x, dict):
                parts.append(x.get("text", ""))
        return "".join(parts)
    return ""


def _snippet(pairs: list[tuple[str, str]], per: int = 70) -> str:
    """Render up to a few "Who: text" lines into one compact conversation hint."""
    out = []
    for who, txt in pairs:
        txt = " ".join(txt.split())
        if not txt:
            continue
        if len(txt) > per:
            txt = txt[:per - 1] + "…"
        out.append(f"{who}: {txt}")
    return "  ·  ".join(out)


# --------------------------------------------------------------------------- #
# OFFLINE: Telegram Desktop JSON export
# --------------------------------------------------------------------------- #
def parse_export(path: str, start: date, end: date, max_group_size: int) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if "chats" not in data:
        raise ValueError("not a full Telegram export (no 'chats' key). Export "
                         "'Personal chats' as Machine-readable JSON.")
    pi = data.get("personal_information") or {}
    owner = f"user{pi.get('user_id')}" if pi.get("user_id") is not None else None

    out = []
    for chat in (data.get("chats") or {}).get("list") or []:
        ctype = chat.get("type", "")
        is_personal = ctype in PERSONAL_TYPES
        is_group = ctype in GROUP_TYPES
        if not (is_personal or is_group):
            continue
        msgs = [(m, _msg_date(m)) for m in chat.get("messages", [])
                if m.get("type") == "message"]
        msgs = [(m, d) for m, d in msgs if d is not None]
        if not msgs:
            continue

        senders = {str(m.get("from_id")) for m, _ in msgs if m.get("from_id")}
        group_size = len(senders)
        if is_group and group_size > max_group_size:
            continue

        in_window = [(m, d) for m, d in msgs if start <= d <= end]
        if not in_window:
            continue
        their = sum(1 for m, _ in in_window
                    if owner is None or str(m.get("from_id")) != owner)
        ordered = sorted(in_window, key=lambda x: x[1])
        snippet = _snippet([
            ("You" if owner and str(m.get("from_id")) == owner else (m.get("from") or "Them"),
             _msg_text(m)) for m, _ in ordered[-3:]])
        first_ever = min(d for _, d in msgs)
        before = [d for _, d in msgs if d < start]
        last_before = max(before) if before else None

        members = []
        target_id = ""
        username = ""
        if is_group:
            for m, _ in msgs:
                if owner and str(m.get("from_id")) == owner:
                    continue
                nm = m.get("from")
                if nm and nm not in members:
                    members.append(nm)
        else:
            # 1:1 — the chat's own id is the peer's user id (works even if the
            # whole conversation was outbound); fall back to a non-owner sender.
            target_id = _num_id(chat.get("id"))
            if target_id == "":
                for m, _ in msgs:
                    fid = str(m.get("from_id")) if m.get("from_id") else None
                    if fid and fid != owner:
                        target_id = _num_id(fid)
                        break

        out.append({
            "name": (chat.get("name") or "(no name)").strip(),
            "username": username,
            "user_id": target_id,
            "is_group": is_group,
            "group_size": group_size if is_group else 2,
            "members": members,
            "msgs_in_window": len(in_window),
            "their_replies": their,
            "first_ever": first_ever,
            "last_before": last_before,
            "snippet": snippet,
        })
    return out


# --------------------------------------------------------------------------- #
# ONLINE: Telethon (read-only). Requires the user's own API id/hash + login.
# --------------------------------------------------------------------------- #
async def gather_live(api_id: int, api_hash: str, session_name: str,
                      start: date, end: date, max_group_size: int,
                      progress=lambda s: None, session_string: str = "") -> list[dict]:
    from telethon import TelegramClient  # imported lazily; only needed for --live
    from telethon.tl.types import User
    from datetime import timezone, timedelta

    # A session_string (Telethon StringSession) authenticates non-interactively —
    # no phone/code prompt. Otherwise fall back to a local file session by name,
    # which logs in interactively the first time and caches the login.
    if session_string:
        from telethon.sessions import StringSession
        session = StringSession(session_string)
    else:
        session = session_name

    # Server-side bound for iter_messages. Telegram filters by UTC, but we bucket
    # by LOCAL calendar date (below) to match the offline export and intuitive
    # "conference day" semantics — so allow a 2-day margin to avoid dropping
    # boundary messages in far-from-UTC timezones.
    end_next = datetime(end.year, end.month, end.day, tzinfo=timezone.utc) + timedelta(days=2)

    # When a login fails (e.g. a revoked session key), Telethon's background
    # sender is left holding the error in a future that, at garbage collection
    # (after this function has already returned and re-raised the real error),
    # prints a confusing "Future exception was never retrieved" traceback.
    # Install a handler that swallows ONLY that specific auth-failure future and
    # delegates everything else to the default handler. It is intentionally not
    # restored afterward: because the noisy future is collected at interpreter
    # shutdown — long after we return — the handler must stay live to catch it.
    # Scoping it to just the auth exception types keeps it from hiding any
    # unrelated error, so leaving it installed is safe even if a larger async
    # app ever calls this.
    loop = asyncio.get_running_loop()
    _default_handler = loop.get_exception_handler()
    _AUTH_NOISE = ("AuthKeyNotFound", "AuthKeyUnregisteredError",
                   "AuthKeyDuplicatedError", "UnauthorizedError")
    def _quiet_handler(lp, ctx):
        if type(ctx.get("exception")).__name__ in _AUTH_NOISE:
            return  # the known login-failure future; the real error is handled above
        (_default_handler or lp.default_exception_handler)(ctx)
    loop.set_exception_handler(_quiet_handler)

    out = []
    client = TelegramClient(session, api_id, api_hash)
    # Explicit lifecycle (clearer than `async with`, and guarantees a clean
    # disconnect even if scanning raises). start() logs in interactively on the
    # first run, then reuses the saved session. It's inside the try so that a
    # failed login (e.g. a revoked session key) still hits the finally and
    # disconnects — otherwise the dangling client emits a noisy "Future
    # exception was never retrieved" traceback at interpreter shutdown.
    try:
        await client.start()
        me = await client.get_me()
        progress(f"Logged in as {('@'+me.username) if me.username else me.first_name}. "
                 "Scanning conversations (read-only)…")
        n = 0
        async for dialog in client.iter_dialogs():
            n += 1
            if n % 50 == 0:
                progress(f"  …scanned {n} conversations")
            ent = dialog.entity
            is_user = dialog.is_user
            is_group = dialog.is_group
            if not (is_user or is_group):
                continue  # skip broadcast channels

            # Cheap pre-filter: a dialog's own `date` is its latest message time.
            # If the whole chat went quiet before the window, it cannot contain
            # any in-window messages — skip it without spending a network peek.
            # (Telegram has no server-side "active between dates" query, so this
            # is what saves us from reading every stale conversation in full.)
            try:
                if dialog.date is not None and dialog.date.astimezone().date() < start:
                    continue
            except (ValueError, OSError):
                pass

            if is_group:
                size = getattr(ent, "participants_count", None) or 0
                if size and size > max_group_size:
                    continue

            # window aggregates + last message before the window + snippet
            win = 0
            their = 0
            last_before = None
            snip = []  # newest-first; reversed for display
            try:
                async for m in client.iter_messages(ent, offset_date=end_next):
                    d = m.date.astimezone().date()  # UTC -> local calendar date
                    if d > end:
                        continue
                    if d >= start:
                        win += 1
                        if not m.out:
                            their += 1
                        if len(snip) < 3:
                            if m.out:
                                who = "You"
                            elif is_user:
                                who = getattr(ent, "first_name", None) or "Them"
                            else:
                                snd = getattr(m, "sender", None)
                                who = getattr(snd, "first_name", None) or "Member"
                            txt = (m.message or "").strip()
                            if txt:
                                snip.append((who, txt))
                    else:
                        last_before = d
                        break
            except Exception:  # noqa: BLE001 — skip chats we can't read
                continue
            if win == 0:
                continue
            snippet = _snippet(list(reversed(snip)))

            oldest = await client.get_messages(ent, limit=1, reverse=True)
            first_ever = oldest[0].date.astimezone().date() if oldest else start

            members = []
            username = ""
            uid = ""
            if is_group:
                size = getattr(ent, "participants_count", 0) or 0
                try:
                    parts = await client.get_participants(ent, limit=max_group_size + 5)
                    if not size:
                        size = len(parts)
                    for p in parts:
                        if isinstance(p, User) and p.id != me.id:
                            members.append(("@" + p.username) if p.username
                                           else ((p.first_name or "") +
                                                 (" " + p.last_name if p.last_name else "")).strip())
                except Exception:  # noqa: BLE001
                    pass
                if size and size > max_group_size:
                    continue
                name = getattr(ent, "title", None) or "(group)"
            else:
                username = ("@" + ent.username) if getattr(ent, "username", None) else ""
                uid = getattr(ent, "id", "")
                name = " ".join(filter(None, [getattr(ent, "first_name", None),
                                              getattr(ent, "last_name", None)])) \
                    or (username or "(no name)")
                size = 2

            out.append({
                "name": name.strip(),
                "username": username,
                "user_id": uid,
                "is_group": is_group,
                "group_size": size,
                "members": [m for m in members if m],
                "msgs_in_window": win,
                "their_replies": their,
                "first_ever": first_ever,
                "last_before": last_before,
                "snippet": snippet,
            })
        progress(f"Done — {len(out)} contacts in the window.")
    finally:
        await client.disconnect()
    return out
