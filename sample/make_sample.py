#!/usr/bin/env python3
"""Generate sample_export.json — 100% synthetic, mimics a Telegram Desktop
export. Used to smoketest conference_crm.py. No real data of any kind:
fictional people, a fictional "Demo Expo" on fictional dates."""
import json

OWNER = 99999  # the (fake) exporting user
# Fictional conference window used by the sample + the docs examples.
# (Deliberately arbitrary dates — not tied to any real event.)


def msg(i, day, who_id, who_name, text):
    return {"id": i, "type": "message", "date": f"2025-09-{day:02d}T10:{i % 60:02d}:00",
            "from": who_name, "from_id": f"user{who_id}", "text": text}


def me(i, day, text):
    return msg(i, day, OWNER, "Me Example", text)


chats = []

# NEW contact met during the window — two-way
chats.append({"name": "Alice Example", "type": "personal_chat", "id": 1001, "messages": [
    msg(1, 11, 1001, "Alice Example", "Great meeting you at the booth!"),
    me(2, 11, "Likewise — let's talk integrations"),
    msg(3, 12, 1001, "Alice Example", "Sending the deck now"),
]})

# REACTIVATED — last talked long before the window, revived during it
chats.append({"name": "Bob Demo", "type": "personal_chat", "id": 1002, "messages": [
    {"id": 1, "type": "message", "date": "2023-05-01T09:00:00", "from": "Bob Demo",
     "from_id": "user1002", "text": "catch up sometime"},
    msg(2, 10, 1002, "Bob Demo", "Long time! You're at the expo too?"),
    me(3, 10, "Ha, yes — coffee?"),
]})

# ONGOING — already in regular recent contact before the window
chats.append({"name": "Carol Sample", "type": "personal_chat", "id": 1003, "messages": [
    {"id": 1, "type": "message", "date": "2025-09-03T12:00:00", "from": "Carol Sample",
     "from_id": "user1003", "text": "weekly check-in"},
    me(2, 11, "At the conference, ping me"),
    msg(3, 13, 1003, "Carol Sample", "nice, see you there"),
]})

# NEW but OUTBOUND-ONLY (you messaged, no reply yet)
chats.append({"name": "Dave Outbound", "type": "personal_chat", "id": 1004, "messages": [
    me(1, 12, "Hey Dave, great chat — here's my Telegram"),
    me(2, 13, "Following up on that lead"),
]})

# Small group (<=15 people) — kept
chats.append({"name": "Deal Room Demo", "type": "private_group", "id": 2001, "messages": [
    msg(1, 11, 1001, "Alice Example", "looping in the team"),
    msg(2, 11, 5001, "Erin Group", "welcome!"),
    me(3, 12, "thanks all"),
]})

# Large group (>15 distinct senders) — should be SKIPPED
big = [msg(i, 12, 6000 + i, f"Member {i}", "gm") for i in range(1, 18)]
chats.append({"name": "Big Public Chat", "type": "private_supergroup", "id": 3001,
              "messages": big})

# A pre-window-only chat (no window activity) — should NOT appear
chats.append({"name": "Old Friend", "type": "personal_chat", "id": 1009, "messages": [
    {"id": 1, "type": "message", "date": "2024-12-01T10:00:00", "from": "Old Friend",
     "from_id": "user1009", "text": "happy holidays"},
]})

export = {
    "about": "Synthetic sample — not real Telegram data.",
    "personal_information": {"user_id": OWNER, "first_name": "Me", "last_name": "Example"},
    "chats": {"about": "synthetic", "list": chats},
}

if __name__ == "__main__":
    with open("sample_export.json", "w", encoding="utf-8") as f:
        json.dump(export, f, indent=2, ensure_ascii=False)
    print("wrote sample_export.json")
