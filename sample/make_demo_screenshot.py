#!/usr/bin/env python3
"""Render demo.html from synthetic 'live-mode-style' rows (with @usernames) so
the README screenshot reflects what the recommended live mode produces.
100% fictional data. Run: `python3 make_demo_screenshot.py` -> demo.html"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import crm_output  # noqa: E402

START, END = date(2025, 9, 10), date(2025, 9, 14)


def person(name, user, uid, first, last, win, their, snippet):
    return {"name": name, "username": "@" + user, "user_id": uid, "is_group": False,
            "group_size": 2, "members": [], "msgs_in_window": win, "their_replies": their,
            "first_ever": first, "last_before": last, "snippet": snippet}


def group(name, size, members, first, win, their, snippet):
    return {"name": name, "username": "", "user_id": "", "is_group": True,
            "group_size": size, "members": members, "msgs_in_window": win,
            "their_replies": their, "first_ever": first, "last_before": None,
            "snippet": snippet}


D = date  # shorthand
aggs = [
    # NEW — met at the event
    person("Alex Rivera", "alexr_growth", 712334455, D(2025, 9, 11), None, 9, 5,
           "Alex Rivera: loved your panel  ·  You: appreciate it — let's set up a call  ·  Alex Rivera: sending times"),
    person("Priya Nair", "priya_adtech", 588211900, D(2025, 9, 11), None, 7, 4,
           "Priya Nair: here's our rate card  ·  You: thanks, reviewing  ·  Priya Nair: ping me anytime"),
    person("Marco Bianchi", "marco_fx", 690155221, D(2025, 9, 12), None, 6, 3,
           "You: great chat at the bar  ·  Marco Bianchi: same! the EU desk is keen"),
    person("Dana Cohen", "dana_partners", 733900112, D(2025, 9, 12), None, 5, 3,
           "Dana Cohen: intro to our BD lead?  ·  You: yes please  ·  Dana Cohen: connecting you now"),
    person("Yuki Tanaka", "yuki_pay", 801224337, D(2025, 9, 13), None, 4, 2,
           "Yuki Tanaka: PSP integration takes ~2 weeks  ·  You: works for us"),
    person("Sven Larsson", "svenl_media", 644120098, D(2025, 9, 13), None, 2, 0,
           "You: here's my Telegram  ·  You: following up on the lead from booth 12"),
    group("Booth 12 Crew", 4, ["@alexr_growth", "@priya_adtech", "@marco_fx"],
          D(2025, 9, 11), 11, 8, "Alex Rivera: who's in for dinner?  ·  You: in  ·  Priya Nair: +1"),
    # REACTIVATED — revived an old contact
    person("Tom Becker", "tombecker", 410982334, D(2024, 2, 3), D(2024, 11, 20), 6, 4,
           "Tom Becker: been a while! you at the expo?  ·  You: yep, let's grab coffee"),
    person("Lena Frost", "lenafrost", 309112400, D(2023, 6, 1), D(2024, 8, 2), 4, 3,
           "Lena Frost: small world!  ·  You: ha, good to reconnect  ·  Lena Frost: let's not lose touch this time"),
    # ONGOING — already talking
    person("Chris Park", "chrisp_ops", 522007781, D(2025, 1, 10), D(2025, 9, 7), 8, 4,
           "Chris Park: see you at the booth  ·  You: on my way  ·  Chris Park: 👍"),
    person("Maria Lopez", "marialopez", 477330021, D(2024, 11, 2), D(2025, 9, 8), 5, 2,
           "You: numbers look good this month  ·  Maria Lopez: agreed, let's scale"),
]

rows = crm_output.finalize(aggs, START, gap_days=30)
crm_output.write_html(rows, "demo.html", "Demo Expo 2025", START, END)
print(f"wrote demo.html ({len(rows)} synthetic contacts)")
