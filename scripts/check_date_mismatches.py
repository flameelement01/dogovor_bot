#!/usr/bin/env python3
"""
Daily cron: compare AMO ОБУЧАЮТСЯ end dates vs ERP educationFinishPlannedAt
for Shymkent+Offline students. Logs mismatches to mismatches_log.json.

ERP data: cached in erp_students_cache.json (update weekly with admin creds).
AMO data: fetched fresh on each run.
"""

import json
import re
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

ASTANA = timezone(timedelta(hours=5))
SCRIPT_DIR = Path(__file__).parent

# AMO
AMO_TOKEN = (
    "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiIsImp0aSI6ImU0NTA3NTEyMTg2ZDcxZTUyNThjYWUyODA2MGZkNm"
    "Q1OTc2NTYyMGExODYwYTg1ODY1MWMzNmFkOTdhYTg0ZDc1MjBlYzc1NjUzOGJhMjRhIn0.eyJhdWQiOiIzZDU1"
    "YWMzNy0wOTUwLTRiZjEtYThkNy0yNGNkYzNkMTA3MjAiLCJqdGkiOiJlNDUwNzUxMjE4NmQ3MWU1MjU4Y2FlMj"
    "gwNjBmZDZkNTk3NjU2MjBhMTg2MGE4NTg2NTFjMzZhZDk3YWE4NGQ3NTIwZWM3NTY1MzhiYTI0YSIsImlhdCI6"
    "MTc4NTM4ODUyNSwibmJmIjoxNzg1Mzg4NTI1LCJleHAiOjE5NDMxMzYwMDAsInN1YiI6IjIyNzU2MjEiLCJncm"
    "FudF90eXBlIjoiIiwiYWNjb3VudF9pZCI6MTg5NTA4NzIsImJhc2VfZG9tYWluIjoiYW1vY3JtLnJ1IiwidmVyc"
    "2lvbiI6Miwic2NvcGVzIjpbInB1c2hfbm90aWZpY2F0aW9ucyIsImZpbGVzIiwiY3JtIiwibm90aWZpY2F0aW9u"
    "cyJdLCJoYXNoX3V1aWQiOiI5MGQ1MjM3ZS0zYjQ0LTQ3YWQtYjQ0Ni05NzAzZmUyZmU1NjkiLCJhcGlfZG9tYW"
    "luIjoiYXBpLWIuYW1vY3JtLnJ1In0.INChlbuC-n1rh6Okm0_5i3SD4KgLp9pChGRWg1mbBkc2pK5KV_fy1Bl7"
    "QqkyJSKsdHECIwaqs6IJuncnSsLmCWR2EiXZS4GoZMOlLkNN8oX6n2T1S4QrnKMKYXMhuPOT9iMysgsOX5zCGN5"
    "BQhuu8VtWS-M5mOi6oxWQ7s3VtiLYimqFUrLOhULGKUWNvXfcHY8uvbLw3SsqNgTMRkBSCkUCo3gCXV_RjRWga"
    "sGhtBL1diWfMUMi316fWJ5hRdR_FEHZTgKHaFCODKyEI_BCK0ADgzvq6fs36rHaSOq5pRtU7f-nBjYKEtbDHakC"
    "PX_d6FKfSHxrVXF598gALbXlcA"
)
AMO_BASE = "https://qadam.amocrm.ru/api/v4"
AMO_PIPELINE = 10798658
AMO_ACTIVE_STAGES = {86591154, 85016530, 85016534}
AMO_FIELD_CITY = 879211
AMO_FIELD_DEPT = 912857
AMO_FIELD_END_DATE = 89203      # Дата окончания обучения
AMO_FIELD_ERP_URL = 912215      # https://crm.aipluscrm.kz/students/{UUID}

UPSELL_PIPELINE = 10798670
AMO_CLOSED_STATUSES = {142, 143}

ERP_CACHE = SCRIPT_DIR / "erp_students_cache.json"
LOG_FILE = SCRIPT_DIR / "mismatches_log.json"
USERS_MAP = SCRIPT_DIR / "users_map.json"

ERP_API = "https://api.aiplus.school"
ERP_USERNAME = "950713301438"
ERP_PASSWORD = "Aa12345678%"
ERP_CACHE_MAX_AGE_DAYS = 7

ERP_SHYM_BRANCHES = {
    "61a32b8f-8049-4d3c-b363-7d3e9d703f86": "Дулати",
    "fd41bf42-f34c-4c58-a85c-55e5d1611873": "Желтоксан",
    "3c45dc5c-1b45-4959-a463-d6fad455235a": "Шаяхметова",
}
ERP_ACTIVE = {"active", "new", "not_started", "frozen"}


def get_field(deal, field_id):
    for f in deal.get("custom_fields_values") or []:
        if f["field_id"] == field_id:
            vals = f.get("values") or []
            return vals[0].get("value", "") if vals else ""
    return ""


def parse_amo_ts(val):
    if not val:
        return None
    try:
        return datetime.fromtimestamp(int(val), tz=ASTANA).date()
    except Exception:
        return None


def parse_erp_date(val):
    if not val or val.startswith("0001"):
        return None
    try:
        return datetime.fromisoformat(val.replace("Z", "+00:00")).astimezone(ASTANA).date()
    except Exception:
        return None


def extract_uuid(url):
    m = re.search(r"/students/([0-9a-f-]{36})", url or "")
    return m.group(1) if m else None


def is_shymkent(deal):
    city = get_field(deal, AMO_FIELD_CITY)
    dept = get_field(deal, AMO_FIELD_DEPT)
    return city == "Шымкент" and dept in ("Offline", "")


def fetch_amo_shymkent():
    print("Fetching AMO ОБУЧАЮТСЯ...", flush=True)
    headers = {"Authorization": f"Bearer {AMO_TOKEN}"}
    page, deals = 1, []
    stages = list(AMO_ACTIVE_STAGES)
    while True:
        # Pass multiple statuses as list of tuples (requests merges duplicate keys)
        params = [
            ("with", "custom_fields"),
            ("limit", 250),
            ("page", page),
        ]
        for i, sid in enumerate(stages):
            params.append((f"filter[statuses][{i}][pipeline_id]", AMO_PIPELINE))
            params.append((f"filter[statuses][{i}][status_id]", sid))
        resp = requests.get(f"{AMO_BASE}/leads", headers=headers, params=params, timeout=30)
        if resp.status_code == 204:
            break
        data = resp.json()
        batch = data.get("_embedded", {}).get("leads", [])
        if not batch:
            break
        for d in batch:
            if is_shymkent(d):
                deals.append(d)
        print(f"  page {page}: {len(deals)} Shymkent deals so far", flush=True)
        if len(batch) < 250:
            break
        page += 1
    print(f"Total AMO Shymkent: {len(deals)}")
    return deals


def erp_login() -> str:
    resp = requests.post(
        f"{ERP_API}/crm-login",
        data={"username": ERP_USERNAME, "password": ERP_PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    d = resp.json()
    if d.get("status") != "success":
        raise RuntimeError(f"ERP login failed: {d.get('error')}")
    return d["data"]["accessToken"]


def refresh_erp_cache():
    print("Refreshing ERP cache...", flush=True)
    token = erp_login()
    headers = {"Authorization": f"Bearer {token}", "Lang": "ru"}
    all_new = []
    for branch_id, branch_name in ERP_SHYM_BRANCHES.items():
        page, rows = 1, 200
        while True:
            resp = requests.post(
                f"{ERP_API}/q/get-students",
                headers=headers,
                json={"page": page, "rowsPerPage": rows,
                      "branches": [branch_id], "statuses": list(ERP_ACTIVE)},
                timeout=30,
            )
            data = resp.json().get("data", {})
            batch = data.get("students", [])
            total = data.get("total", 0)
            all_new.extend(batch)
            print(f"  {branch_name} page {page}: {len(all_new)}", flush=True)
            if not batch or len(all_new) >= total or len(batch) < rows:
                break
            page += 1
        print(f"  → {branch_name}: done")

    old_others = []
    if ERP_CACHE.exists():
        with open(ERP_CACHE) as f:
            old = json.load(f)
        old_others = [s for s in old if s.get("branch", {}).get("id") not in ERP_SHYM_BRANCHES]

    merged = old_others + all_new
    with open(ERP_CACHE, "w") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    print(f"ERP cache refreshed: {len(all_new)} Shymkent students")


def load_erp():
    # Auto-refresh if cache is missing or older than ERP_CACHE_MAX_AGE_DAYS
    if ERP_CACHE.exists():
        age_days = (datetime.now().timestamp() - ERP_CACHE.stat().st_mtime) / 86400
        if age_days > ERP_CACHE_MAX_AGE_DAYS:
            print(f"ERP cache is {age_days:.0f} days old — refreshing...", flush=True)
            refresh_erp_cache()
    else:
        refresh_erp_cache()

    print(f"Loading ERP cache...", flush=True)
    with open(ERP_CACHE) as f:
        all_students = json.load(f)
    active = {
        s["id"]: s
        for s in all_students
        if s.get("branch", {}).get("id") in ERP_SHYM_BRANCHES
        and s.get("status") in ERP_ACTIVE
    }
    print(f"ERP Shymkent active: {len(active)}")
    return active


def load_users():
    try:
        with open(USERS_MAP) as f:
            return {int(k): v for k, v in json.load(f).items()}
    except Exception:
        return {}


def compare(amo_deals, erp_by_uuid, users):
    today = datetime.now(ASTANA).date()
    matches, no_uuid, uuid_missing, no_date = 0, 0, 0, 0
    erp_newer, amo_newer = [], []

    for deal in amo_deals:
        erp_url = get_field(deal, AMO_FIELD_ERP_URL)
        uuid = extract_uuid(erp_url)
        if not uuid:
            no_uuid += 1
            continue
        erp = erp_by_uuid.get(uuid)
        if not erp:
            uuid_missing += 1
            continue

        amo_date = parse_amo_ts(get_field(deal, AMO_FIELD_END_DATE))
        erp_date = parse_erp_date(erp.get("educationFinishPlannedAt", ""))
        if not amo_date or not erp_date:
            no_date += 1
            continue

        diff = (erp_date - amo_date).days
        rec = {
            "name": f"{erp.get('lastName','')} {erp.get('firstName','')}",
            "amo_date": amo_date.isoformat(),
            "erp_date": erp_date.isoformat(),
            "diff_days": diff,
            "deal_id": deal.get("id"),
            "manager": users.get(deal.get("responsible_user_id"),
                                  str(deal.get("responsible_user_id"))),
            "branch": erp.get("branch", {}).get("name", ""),
            "uuid": uuid,
        }
        if diff == 0:
            matches += 1
        elif diff > 0:
            erp_newer.append(rec)
        else:
            amo_newer.append(rec)

    print(f"\nStats: no_uuid={no_uuid}, uuid_missing={uuid_missing}, no_date={no_date}")
    return matches, erp_newer, amo_newer


TASK_MARKER = "[ERP-DATE-CHECK]"  # unique marker to detect existing tasks

TG_TOKEN = "8857346192:AAGIsC33kOGdit18p-LIY6GgPBwdCgJZV-M"
TG_CHAT_ID = 603785864


def send_telegram(text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=15,
        )
    except Exception:
        pass


def get_contact_id(deal_id, headers):
    """Return main contact_id for a deal."""
    resp = requests.get(
        f"{AMO_BASE}/leads/{deal_id}",
        headers=headers,
        params={"with": "contacts"},
        timeout=15,
    )
    if resp.status_code != 200:
        return None
    contacts = resp.json().get("_embedded", {}).get("contacts", [])
    for c in contacts:
        if c.get("is_main"):
            return c["id"]
    return contacts[0]["id"] if contacts else None


def has_active_upsell(contact_id, headers):
    """Return True if contact has an active (non-closed) deal in the upsell pipeline."""
    page = 1
    while True:
        resp = requests.get(
            f"{AMO_BASE}/leads",
            headers=headers,
            params={
                "filter[pipeline_id]": UPSELL_PIPELINE,
                "filter[contact_id]": contact_id,
                "limit": 250,
                "page": page,
            },
            timeout=15,
        )
        if resp.status_code != 200:
            return False
        deals = resp.json().get("_embedded", {}).get("leads", [])
        if not deals:
            return False
        for d in deals:
            if d.get("status_id") not in AMO_CLOSED_STATUSES:
                return True
        if len(deals) < 250:
            return False
        page += 1


def has_open_erp_task(deal_id, headers):
    """Return True if there's already an open date-mismatch task on this deal."""
    resp = requests.get(
        f"{AMO_BASE}/tasks",
        headers=headers,
        params={"filter[entity_id]": deal_id, "filter[entity_type]": "leads"},
        timeout=15,
    )
    if resp.status_code != 200:
        return False
    tasks = resp.json().get("_embedded", {}).get("tasks", [])
    return any(
        not t.get("is_completed") and TASK_MARKER in (t.get("text") or "")
        for t in tasks
    )


def create_amo_task(rec, responsible_user_id, headers):
    """Create a task on the deal for the responsible manager."""
    deadline = datetime.now(ASTANA) + timedelta(days=3)
    deadline_ts = int(deadline.timestamp())
    text = (
        f"{TASK_MARKER} Дата окончания обучения не совпадает с ERP.\n"
        f"В AMO: {rec['amo_date']} | В ERP: {rec['erp_date']} (+{rec['diff_days']} дн)\n"
        f"Исправьте дату в поле «Дата окончания обучения»."
    )
    payload = [{
        "text": text,
        "complete_till": deadline_ts,
        "entity_id": rec["deal_id"],
        "entity_type": "leads",
        "responsible_user_id": responsible_user_id,
        "task_type_id": 1891435,  # Чек
    }]
    resp = requests.post(f"{AMO_BASE}/tasks", headers=headers, json=payload, timeout=15)
    return resp.status_code in (200, 201)


def create_tasks_for_mismatches(erp_newer, amo_deals):
    """For each ERP>AMO mismatch, create an AMO task if one doesn't exist yet."""
    if not erp_newer:
        return
    headers = {
        "Authorization": f"Bearer {AMO_TOKEN}",
        "Content-Type": "application/json",
    }
    deal_to_user = {d["id"]: d.get("responsible_user_id") for d in amo_deals}

    created, skipped_task, skipped_upsell = 0, 0, 0
    real_errors = []  # mismatches without active upsell

    for rec in sorted(erp_newer, key=lambda x: -x["diff_days"]):
        deal_id = rec["deal_id"]

        # Skip if student is in active upsell (waiting for full payment — will auto-resolve)
        contact_id = get_contact_id(deal_id, headers)
        if contact_id and has_active_upsell(contact_id, headers):
            skipped_upsell += 1
            print(f"  ⏳ {rec['name']:28s} — апсейл активен, пропускаем (deal #{deal_id})")
            continue

        real_errors.append(rec)

        # Skip if task already exists
        if has_open_erp_task(deal_id, headers):
            skipped_task += 1
            print(f"  ↩ {rec['name']:28s} — задача уже есть, пропускаем")
            continue

        responsible_id = deal_to_user.get(deal_id)
        if create_amo_task(rec, responsible_id, headers):
            created += 1
            print(f"  ✅ {rec['name']:28s} — задача создана (deal #{deal_id})")
        else:
            print(f"  ❌ {rec['name']:28s} — ошибка создания задачи")

    print(f"\nЗадачи: создано={created}, пропущено (задача есть)={skipped_task}, пропущено (апсейл)={skipped_upsell}")
    return real_errors


def load_log():
    if LOG_FILE.exists():
        with open(LOG_FILE) as f:
            return json.load(f)
    return {"runs": []}


def save_log(log):
    with open(LOG_FILE, "w") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def print_mismatches(erp_newer, amo_newer):
    if erp_newer:
        print(f"\n🔴 ERP > AMO — нужно обновить AMO ({len(erp_newer)} шт):")
        for r in sorted(erp_newer, key=lambda x: -x["diff_days"]):
            print(f"  {r['name']:28s} AMO:{r['amo_date']} → ERP:{r['erp_date']} "
                  f"(+{r['diff_days']}д) [{r['branch']}] #{r['deal_id']}")

    if amo_newer:
        print(f"\n🟡 AMO > ERP — продление (AMO новее, {len(amo_newer)} шт):")
        for r in sorted(amo_newer, key=lambda x: x["diff_days"]):
            print(f"  {r['name']:28s} AMO:{r['amo_date']} → ERP:{r['erp_date']} "
                  f"({r['diff_days']}д) [{r['branch']}]")


def main():
    now_str = datetime.now(ASTANA).strftime("%Y-%m-%d %H:%M")
    print(f"=== Date mismatch check — {now_str} (Astana) ===\n")

    erp_by_uuid = load_erp()
    amo_deals = fetch_amo_shymkent()
    users = load_users()

    matches, erp_newer, amo_newer = compare(amo_deals, erp_by_uuid, users)

    print(f"\n{'='*50}")
    print(f"✅ Совпадают:             {matches}")
    print(f"🔴 ERP > AMO (обновить): {len(erp_newer)}")
    print(f"🟡 AMO > ERP (продление):{len(amo_newer)}")

    print_mismatches(erp_newer, amo_newer)

    # Create AMO tasks for ERP>AMO mismatches
    real_errors = []
    if erp_newer:
        print(f"\n📋 Создаём задачи в AMO...")
        real_errors = create_tasks_for_mismatches(erp_newer, amo_deals)

    # Send Telegram report
    lines = [f"📊 <b>Ежедневный чек дат — {now_str} (Шымкент)</b>"]
    lines.append(f"✅ Совпадают: {matches}")
    lines.append(f"🔴 ERP &gt; AMO: {len(erp_newer)} (из них в апсейле: {len(erp_newer) - len(real_errors)})")
    lines.append(f"🟡 AMO &gt; ERP (продление): {len(amo_newer)}")

    if real_errors:
        lines.append(f"\n⚠️ <b>Реальных ошибок: {len(real_errors)} — задачи созданы</b>")
        for r in sorted(real_errors, key=lambda x: -x["diff_days"]):
            amo_link = f"https://qadam.amocrm.ru/leads/detail/{r['deal_id']}"
            lines.append(
                f"• <a href='{amo_link}'>{r['name']}</a> [{r['branch']}]\n"
                f"  AMO: {r['amo_date']} → ERP: {r['erp_date']} (+{r['diff_days']} дн)"
            )
    else:
        lines.append("\n✅ <b>Реальных ошибок нет</b> — все мисматчи в апсейле")

    send_telegram("\n".join(lines))

    # Append to log
    log = load_log()
    log["runs"].append({
        "ts": now_str,
        "matched": matches,
        "erp_newer": len(erp_newer),
        "amo_newer": len(amo_newer),
        "erp_newer_details": erp_newer,
        "amo_newer_details": amo_newer,
    })
    log["runs"] = log["runs"][-30:]
    save_log(log)
    print(f"\nLog saved to {LOG_FILE}")


if __name__ == "__main__":
    main()
