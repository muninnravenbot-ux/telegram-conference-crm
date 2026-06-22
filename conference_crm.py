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
    python3 conference_crm.py --export result.json --conference "Acme Expo 2026" \
        --start 2026-09-10 --end 2026-09-12
    python3 conference_crm.py --live --conference "Acme Expo 2026" \
        --start 2026-09-10 --end 2026-09-12         # uses TG_API_ID/TG_API_HASH or prompts
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date, datetime

import crm_output
import crm_sources

FILTER_NOTE = """\
Heads-up on what's included (so there are no surprises):
  • Your 1:1 chats and SMALL groups (<= {maxg} people) are included.
  • Large / public groups (> {maxg} people) are skipped — too noisy for a CRM.
  • Only chats with at least one message during the conference days are listed.
  • Everything is READ-ONLY. Nothing is ever sent, deleted, or changed.
"""


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        val = ""
    return val or default


def _ask_date(prompt: str) -> date:
    while True:
        raw = _ask(prompt)
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            print("  Please use YYYY-MM-DD (e.g. 2025-09-10).")


def wizard(args: argparse.Namespace) -> argparse.Namespace:
    print("\n📇  Telegram Post-Conference CRM\n" + "-" * 40)
    print(FILTER_NOTE.format(maxg=args.max_group_size))
    args.conference = args.conference or _ask("Conference name", "My Conference")
    print("\nWhen were the conference days? (the window we'll scan)")
    args.start = args.start or _ask_date("  First day (YYYY-MM-DD)").isoformat()
    args.end = args.end or _ask_date("  Last day  (YYYY-MM-DD)").isoformat()

    if not args.live and not args.export:
        print("\nWhere should we read your Telegram from?")
        print("  1) LIVE  — log in with your own Telegram API key (gets @usernames + IDs)")
        print("  2) EXPORT — a Telegram Desktop JSON export file (offline, names only)")
        choice = _ask("Choose 1 or 2", "1")
        if choice.strip().startswith("2"):
            args.export = _ask("Path to result.json")
        else:
            args.live = True

    if args.live and not (args.api_id and args.api_hash):
        print("\nLIVE mode needs your personal Telegram API credentials (free, 1 min):")
        print("  → Go to https://my.telegram.org → API development tools → create an app")
        print("  → Copy the api_id (a number) and api_hash (a long string)")
        print("  Your login session is saved locally as ./conference.session and never shared.")
        args.api_id = args.api_id or _ask("  api_id")
        args.api_hash = args.api_hash or _ask("  api_hash")
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
        session_string = args.session_string or os.environ.get("TG_SESSION_STRING") \
            or os.environ.get("TELEGRAM_SESSION", "")
        if not (api_id and api_hash):
            print("ERROR: live mode needs --api-id/--api-hash (or TG_API_ID/TG_API_HASH).",
                  file=sys.stderr)
            return 2
        try:
            aggs = asyncio.run(crm_sources.gather_live(
                int(api_id), str(api_hash), args.session, start, end,
                args.max_group_size, progress=lambda s: print("  " + s),
                session_string=session_string))
        except ImportError:
            print("ERROR: live mode needs Telethon. Install it:\n"
                  "    python3 -m pip install telethon", file=sys.stderr)
            return 2
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
    print(f"\n✅  {len(rows)} contacts from '{args.conference}' "
          f"({start} → {end})")
    print(f"     🟢 NEW {counts['NEW']}   🟡 REACTIVATED {counts['REACTIVATED']}   "
          f"⚪ ONGOING {counts['ONGOING']}")
    print(f"\n   📄 {csv_path}   (open in Google Sheets / Excel)")
    print(f"   🌐 {html_path}  (open in your browser — searchable, with follow-up checkboxes)")
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
        args = wizard(args)

    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
