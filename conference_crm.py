#!/usr/bin/env python3
"""
conference_crm.py — Turn your Telegram into a post-conference mini-CRM.

Lists everyone you spoke with during a conference's days and sorts them into
NEW (met at the event) / REACTIVATED (revived old contact) / ONGOING, with
@usernames, numeric Telegram IDs, clickable "open chat" links, and a follow-up
checkbox you can tick off. Outputs a CSV and a nice self-contained HTML app.

Two ways to feed it your data:
  • LIVE  (recommended) — logs into Telegram with YOUR OWN api id/hash and reads
    your chats directly. Gets @usernames + numeric IDs. Read-only.
  • EXPORT (offline)    — parses a Telegram Desktop JSON export. No login, no
    network. Gets names + numeric IDs, but Telegram exports omit @usernames.

Run with no arguments for a guided wizard:
    python3 conference_crm.py

Or non-interactively, e.g.:
    python3 conference_crm.py --export result.json --conference "Demo Expo" \
        --start 2025-09-10 --end 2025-09-14
    python3 conference_crm.py --live --conference "Demo Expo" \
        --start 2025-09-10 --end 2025-09-14         # uses TG_API_ID/TG_API_HASH or prompts
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date, datetime

import crm_output
import crm_sources

WELCOME = """\
👋  Let's turn your Telegram into a post-conference CRM.

In about a minute you'll have a tidy list of everyone you talked to at the
event — who you just met, who you reconnected with, and who still needs a reply.

First, the promises:
  ✓ Read-only — I never send, delete, or change anything in your Telegram.
  ✓ Local — your data stays on this computer and goes nowhere else.
  ✓ I cover your 1:1 chats and small groups (up to {maxg} people).
  ✓ Big public groups (over {maxg}) are skipped — they'd just be noise.
"""


class _Abort(Exception):
    """Raised to bail out of the wizard cleanly (Ctrl-D / Ctrl-C / closed stdin)."""


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"{prompt}{suffix} ").strip()
    except (EOFError, KeyboardInterrupt):
        raise _Abort
    return val or default


def _ask_date(prompt: str) -> date:
    # Bounded retries so a stream of bad/empty input can't loop forever.
    for _ in range(6):
        raw = _ask(prompt)
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            print("   ↳ I need the format YYYY-MM-DD, e.g. 2025-09-10. Try again:")
    raise _Abort


def wizard(args: argparse.Namespace) -> argparse.Namespace:
    print("\n" + "📇  Telegram Post-Conference CRM".center(64))
    print("═" * 64)
    print(WELCOME.format(maxg=args.max_group_size))

    args.conference = args.conference or _ask(
        "📛  What's the event called?", "My Conference")

    print("\n📅  Which days was it? (I'll scan just that window — dates as YYYY-MM-DD)")
    if not args.start:
        args.start = _ask_date("    First day →").isoformat()
    if not args.end:
        args.end = _ask_date("    Last day  →").isoformat()

    if not args.live and not args.export:
        print("\n🔌  How should I read your chats?\n")
        print("    1) Live  — log in with your own Telegram key. Best results:")
        print("              real @usernames, IDs, and one-click 'open chat' links.")
        print("    2) File  — point me at a Telegram Desktop export instead. No login,")
        print("              but Telegram leaves @usernames out of exports.\n")
        choice = _ask("    Pick 1 or 2", "1")
        if choice.strip().startswith("2"):
            print("\n    📄 In Telegram Desktop: Settings → Advanced → Export Telegram data")
            print("       → tick only 'Personal chats', format 'Machine-readable JSON'.")
            args.export = _ask("    Path to your result.json →")
        else:
            args.live = True

    if args.live and not (args.api_id and args.api_hash):
        print("\n🔑  Live mode uses your own Telegram API key — free and takes a minute:")
        print("       1. Open https://my.telegram.org  →  'API development tools'")
        print("       2. Create an app (any name) and copy the two values below.")
        print("    Your login stays on this machine (./conference.session) and is never shared.\n")
        args.api_id = args.api_id or _ask("    api_id   (a number) →")
        args.api_hash = args.api_hash or _ask("    api_hash (a long string) →")

    print("\n✨  Perfect — building your CRM now. Sit tight…")
    return args


def run(args: argparse.Namespace) -> int:
    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()
    if end < start:
        print("ERROR: --end is before --start", file=sys.stderr)
        return 2

    if args.live:
        api_id = args.api_id or os.environ.get("TG_API_ID") or os.environ.get("TELEGRAM_API_ID")
        api_hash = args.api_hash or os.environ.get("TG_API_HASH") or os.environ.get("TELEGRAM_API_HASH")
        if not (api_id and api_hash):
            print("ERROR: live mode needs --api-id/--api-hash (or TG_API_ID/TG_API_HASH).",
                  file=sys.stderr)
            return 2
        try:
            api_id_int = int(str(api_id).strip())
        except ValueError:
            print("ERROR: api_id must be a number (the api_id from my.telegram.org).",
                  file=sys.stderr)
            return 2
        # Keep the session name to a safe filename — it becomes <name>.session on disk.
        safe_session = "".join(c for c in args.session if c.isalnum() or c in ("_", "-")) \
            or "conference"
        # Session precedence: an explicit --session-string flag always wins. Otherwise
        # fall back to an env session string — but NOT when a saved interactive login
        # already exists on disk. A stray TELEGRAM_SESSION (e.g. sourced from another
        # project's .env) silently shadowing a real login is a nasty footgun.
        session_string = args.session_string.strip() if args.session_string else ""
        if not session_string:
            env_str = (os.environ.get("TG_SESSION_STRING")
                       or os.environ.get("TELEGRAM_SESSION", "")).strip()
            if env_str and os.path.exists(safe_session + ".session"):
                print(f"  Note: ignoring a TELEGRAM_SESSION/TG_SESSION_STRING from the "
                      f"environment in favor of your saved {safe_session}.session login "
                      f"(pass --session-string to use the env value instead).",
                      file=sys.stderr)
            else:
                session_string = env_str
        try:
            aggs = asyncio.run(crm_sources.gather_live(
                api_id_int, str(api_hash), safe_session, start, end,
                args.max_group_size, progress=lambda s: print("  " + s, flush=True),
                session_string=session_string))
        except ImportError:
            print("ERROR: live mode needs Telethon. Install it:\n"
                  "    python3 -m pip install telethon", file=sys.stderr)
            return 2
        except Exception as e:  # noqa: BLE001 — turn cryptic auth crashes into guidance
            nm = type(e).__name__
            if "Password" in nm:  # SessionPasswordNeededError — the account has 2FA
                print("ERROR: this account has two-factor (2FA) login enabled and needs "
                      "its password.", file=sys.stderr)
                print("  Run in an interactive terminal so you can type the password, or "
                      "pass an already-authenticated --session-string.", file=sys.stderr)
                return 2
            if any(s in nm for s in ("AuthKey", "Unauthorized", "SessionRevoked",
                                     "Unregistered")):
                print("ERROR: your Telegram login is no longer valid — the session was "
                      "revoked or expired.", file=sys.stderr)
                print("  Fix: clear the saved session and log in again:", file=sys.stderr)
                print(f"      rm -f {safe_session}.session", file=sys.stderr)
                print("      then re-run; you'll get a fresh phone + code login.",
                      file=sys.stderr)
                print("  Also unset any stale TELEGRAM_SESSION / TG_SESSION_STRING in your "
                      "environment — an old one can shadow a good login.", file=sys.stderr)
                return 2
            raise
    else:
        if not args.export:
            print("ERROR: provide --export PATH or use --live (or run with no args "
                  "for the wizard).", file=sys.stderr)
            return 2
        try:
            aggs = crm_sources.parse_export(args.export, start, end, args.max_group_size)
        except FileNotFoundError:
            print(f"ERROR: export not found: {args.export}", file=sys.stderr)
            return 2
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2

    rows = crm_output.finalize(aggs, start, args.reactivate_gap_days)
    if not rows:
        print("No conversations found in that window. Check the dates and that your "
              "data actually covers those days.")
        return 0

    csv_path = args.out_prefix + ".csv"
    html_path = args.out_prefix + ".html"
    crm_output.write_csv(rows, csv_path)
    crm_output.write_html(rows, html_path, args.conference, start, end)

    counts = {"NEW": 0, "REACTIVATED": 0, "ONGOING": 0}
    for r in rows:
        counts[r["Status"]] = counts.get(r["Status"], 0) + 1
    print(f"\n🎉  Done! {len(rows)} people from '{args.conference}' ({start} → {end}):")
    print(f"     🟢 {counts['NEW']} new (met there)   "
          f"🟡 {counts['REACTIVATED']} reconnected   "
          f"⚪ {counts['ONGOING']} already talking")
    print("\n   Here's your CRM:")
    print(f"     🌐 {html_path}   ← open this in your browser (search, links, follow-up ticks)")
    print(f"     📄 {csv_path}   ← or this in Google Sheets / Excel")
    print("\n   Tip: start with the 🟢 NEW folks — those connections fade fastest. "
          "Good luck! 🙌")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build a post-conference Telegram CRM.")
    ap.add_argument("--conference", help="conference name (for the report header)")
    ap.add_argument("--start", help="first conference day YYYY-MM-DD")
    ap.add_argument("--end", help="last conference day YYYY-MM-DD")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--live", action="store_true", help="read live from Telegram (Telethon)")
    src.add_argument("--export", help="path to a Telegram Desktop result.json")
    ap.add_argument("--api-id", help="Telegram api_id (live mode; or env TG_API_ID)")
    ap.add_argument("--api-hash", help="Telegram api_hash (live mode; or env TG_API_HASH)")
    ap.add_argument("--session", default="conference", help="Telethon session name (live)")
    ap.add_argument("--session-string", default="",
                    help="Telethon StringSession for non-interactive login "
                         "(or env TG_SESSION_STRING / TELEGRAM_SESSION)")
    ap.add_argument("--out-prefix", default="conference_crm", help="output file prefix")
    ap.add_argument("--max-group-size", type=int, default=15)
    ap.add_argument("--reactivate-gap-days", type=int, default=30)
    ap.add_argument("--no-wizard", action="store_true", help="never prompt; use args only")
    args = ap.parse_args(argv)

    needs = not (args.start and args.end and (args.live or args.export) and args.conference)
    if needs and not args.no_wizard and sys.stdin.isatty():
        try:
            args = wizard(args)
        except _Abort:
            print("\n\n👋  No worries — stopped before doing anything. Run me again anytime!")
            return 1

    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
