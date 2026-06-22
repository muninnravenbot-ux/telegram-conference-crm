# Agent instructions

You are helping a user build a **post-conference mini-CRM** from their Telegram:
a list of everyone they spoke with during a conference's days, classified NEW
(met at the event) / REACTIVATED (revived old contact) / ONGOING, with
@usernames, numeric Telegram IDs, clickable chat links, a snippet of what was
discussed, and a follow-up checkbox.

Entry point: `conference_crm.py`. Modules: `crm_sources.py` (data in),
`crm_output.py` (CSV + self-contained HTML out). Read-only.

## Flow

1. **Collect inputs** (ask if not given): conference **name**, **start** and
   **end** dates (`YYYY-MM-DD`), and which source to use.

2. **Pick a source:**
   - **Live (best — gets @usernames + IDs):** needs `telethon`
     (`pip install telethon`) and the user's own `api_id`/`api_hash` from
     <https://my.telegram.org>. Login is interactive (phone + code), session
     saved locally as `./conference.session`.
     ```bash
     python3 conference_crm.py --live --conference "<NAME>" --start <S> --end <E> \
         --api-id <ID> --api-hash <HASH>
     ```
   - **Offline export (no creds):** user exports Telegram **Desktop** →
     Settings → Advanced → Export Telegram data → untick all but **Personal
     chats**, media off, **Machine-readable JSON** → `result.json`.
     ```bash
     python3 conference_crm.py --export result.json --conference "<NAME>" \
         --start <S> --end <E>
     ```

3. **Verify on the bundled synthetic data first** (never touch real data until
   the tool runs clean):
   ```bash
   python3 conference_crm.py --export sample/sample_export.json \
       --conference "Demo Expo" --start 2025-09-10 --end 2025-09-14 --no-wizard
   ```
   Expect: 3 NEW, 1 REACTIVATED, 1 ONGOING; large group + pre-window chat excluded.

4. **Deliver:** the run writes `conference_crm.csv` and `conference_crm.html`.
   Tell the user to open the HTML in a browser (searchable, follow-up
   checkboxes). Summarize counts, NEW contacts first.

## Rules

- **Never** read, print, copy, or commit the user's `result.json`,
  `*.session`, or the generated CSV/HTML. They are private and `.gitignore`d.
- **Never** weaken the privacy story: offline mode stays offline; live mode
  talks only to Telegram's own API with the user's own key. Add no other
  network calls, no telemetry.
- Default filters: 1:1 chats + groups ≤ `--max-group-size` (15); larger groups
  skipped. Reactivation gap default 30 days. Both are flags.
- If nothing shows up, re-check the dates and that the data covers them.
