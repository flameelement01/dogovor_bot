#!/usr/bin/env python3
"""
Daily manager Telegram report from AMO CRM.
Formula: total = call_minutes + meetings×15 + contracts_from_meetings×5
Plan: 120 minutes/day.
"""

import os, requests
from datetime import datetime, timezone, timedelta
from collections import defaultdict

ASTANA = timezone(timedelta(hours=5))

TOKEN = os.environ.get("AMOCRM_TOKEN") or (
    "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiIsImp0aSI6ImU0NTA3NTEyMTg2ZDcxZTUyNThjYWUyODA2MGZkNmQ1OTc2NTYyMGExODYwYTg1ODY1MWMzNmFkOTdhYTg0ZDc1MjBlYzc1NjUzOGJhMjRhIn0.eyJhdWQiOiIzZDU1YWMzNy0wOTUwLTRiZjEtYThkNy0yNGNkYzNkMTA3MjAiLCJqdGkiOiJlNDUwNzUxMjE4NmQ3MWU1MjU4Y2FlMjgwNjBmZDZkNTk3NjU2MjBhMTg2MGE4NTg2NTFjMzZhZDk3YWE4NGQ3NTIwZWM3NTY1MzhiYTI0YSIsImlhdCI6MTc4NTM4ODUyNSwibmJmIjoxNzg1Mzg4NTI1LCJleHAiOjE5NDMxMzYwMDAsInN1YiI6IjIyNzU2MjEiLCJncmFudF90eXBlIjoiIiwiYWNjb3VudF9pZCI6MTg5NTA4NzIsImJhc2VfZG9tYWluIjoiYW1vY3JtLnJ1IiwidmVyc2lvbiI6Miwic2NvcGVzIjpbInB1c2hfbm90aWZpY2F0aW9ucyIsImZpbGVzIiwiY3JtIiwibm90aWZpY2F0aW9ucyJdLCJoYXNoX3V1aWQiOiI5MGQ1MjM3ZS0zYjQ0LTQ3YWQtYjQ0Ni05NzAzZmUyZmU1NjkiLCJhcGlfZG9tYWluIjoiYXBpLWIuYW1vY3JtLnJ1In0.INChlbuC-n1rh6Okm0_5i3SD4KgLp9pChGRWg1mbBkc2pK5KV_fy1Bl7QqkyJSKsdHECIwaqs6IJuncnSsLmCWR2EiXZS4GoZMOlLkNN8oX6n2T1S4QrnKMKYXMhuPOT9iMysgsOX5zCGN5BQhuu8VtWS-M5mOi6oxWQ7s3VtiLYimqFUrLOhULGKUWNvXfcHY8uvbLw3SsqNgTMRkBSCkUCo3gCXV_RjRWgasGhtBL1diWfMUMi316fWJ5hRdR_FEHZTgKHaFCODKyEI_BCK0ADgzvq6fs36rHaSOq5pRtU7f-nBjYKEtbDHakCPX_d6FKfSHxrVXF598gALbXlcA"
)
AMO_BASE = "https://qadam.amocrm.ru/api/v4"
H = {"Authorization": f"Bearer {TOKEN}"}

TG_TOKEN  = os.environ.get("BOT_TOKEN") or "8857346192:AAGIsC33kOGdit18p-LIY6GgPBwdCgJZV-M"
TG_CHAT_ID = 603785864

PLAN_MIN = 120

MANAGERS = {
    9400090:  "Зуппарова Умида",
    9400138:  "Калшабек Нурислам",
    9400162:  "Мухамеджан Аружан",
    13456338: "Мирхан Диас",
    13630778: "Ермаханбетова Зияда",
    13630786: "Мамадияров Рауль",
    13824610: "Байзакова Акжибек",
    13887778: "Торебек Аяжан",
    13887806: "Айнур Шынараловна",
}

STAGE_MEETING      = 46560529  # ВСТРЕЧА СОСТОЯЛАСЬ (Новые продажи)
STAGE_PREPAY1      = 59636926  # ПРЕДОПЛАТА получена №1
STAGE_FULL_PAYMENT = 33378673  # ПОЛНАЯ ОПЛАТА ПОЛУЧЕНА (клиент заплатил сразу)

GSHEETS_ID = "1ZJvry0Lsz5S3MervhngUDOZuYhS-zPCu8JDhAI4yFJE"
GSHEETS_CREDS_JSON = os.environ.get("GSHEETS_CREDS") or open(
    os.path.expanduser("~/.gsheets_creds.json")).read() if os.path.exists(
    os.path.expanduser("~/.gsheets_creds.json")) else ""

SHEET_TABS = {
    "Аружан":  9400162,
    "Нурислам": 9400138,
    "Умида":   9400090,
    "Рауль":   13630786,
    "Зияда":   13630778,
    "Акжибек": 13824610,
    "Диас":    13456338,
    "Айнура":  13887806,
    "Аяжан":   13887778,
}


def today_ts_range():
    now = datetime.now(ASTANA)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end   = now.replace(hour=23, minute=59, second=59, microsecond=0)
    return int(start.timestamp()), int(end.timestamp())


def fetch_events(event_types: list, ts_from: int, ts_to: int) -> list:
    results = []
    page = 1
    while True:
        params = [("limit", 250), ("page", page),
                  ("filter[created_at][from]", ts_from),
                  ("filter[created_at][to]",   ts_to)]
        for t in event_types:
            params.append(("filter[type][]", t))
        r = requests.get(f"{AMO_BASE}/events", headers=H, params=params, timeout=15)
        if r.status_code == 204:
            break
        items = r.json().get("_embedded", {}).get("events", [])
        if not items:
            break
        results.extend(items)
        if len(items) < 250:
            break
        page += 1
    return results


def fetch_notes_batch(entity_type: str, note_ids: list) -> dict:
    endpoint = "contacts" if entity_type == "contact" else "leads"
    result = {}
    for i in range(0, len(note_ids), 100):
        chunk = note_ids[i:i + 100]
        params = [("limit", 250)] + [("filter[id][]", nid) for nid in chunk]
        r = requests.get(f"{AMO_BASE}/{endpoint}/notes", headers=H, params=params, timeout=15)
        if r.status_code != 200:
            continue
        for n in r.json().get("_embedded", {}).get("notes", []):
            result[n["id"]] = n.get("params", {})
    return result


def fetch_payments_today() -> dict:
    """Return {uid: payment_sum} from Google Sheets."""
    if not GSHEETS_CREDS_JSON:
        return {}
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        import json as _json
        creds_data = _json.loads(GSHEETS_CREDS_JSON)
        scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
        creds  = Credentials.from_service_account_info(creds_data, scopes=scopes)
        gc     = gspread.authorize(creds)
        sh     = gc.open_by_key(GSHEETS_ID)
        today  = datetime.now(ASTANA).strftime("%d.%m.%Y")
        result = {}
        for tab, uid in SHEET_TABS.items():
            try:
                rows  = sh.worksheet(tab).get_all_values()
                total = sum(
                    _parse_amount(r[2])
                    for r in rows[1:]
                    if len(r) > 8 and r[8].strip() == today and r[2].strip()
                )
                result[uid] = total
            except Exception:
                pass
        return result
    except Exception as e:
        print(f"[sheets] {e}")
        return {}


def _parse_amount(s: str) -> float:
    s = s.replace('\xa0', '').replace(' ', '').replace(',', '.')
    try:
        return float(s)
    except Exception:
        return 0.0


def send_telegram(text: str):
    requests.post(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        json={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML"},
        timeout=10,
    )


def progress_bar(pct: int, width: int = 10) -> str:
    filled = round(pct / 100 * width)
    return "▓" * filled + "░" * (width - filled)


def build_report() -> str:
    """Build and return the report text (does NOT send Telegram)."""
    ts_from, ts_to = today_ts_range()
    date_str = datetime.now(ASTANA).strftime("%d.%m.%Y")

    call_events = fetch_events(["incoming_call", "outgoing_call"], ts_from, ts_to)
    mgr_calls_raw = [e for e in call_events if e.get("created_by") in MANAGERS]

    contact_note_ids, lead_note_ids = [], []
    for e in mgr_calls_raw:
        va = e.get("value_after") or []
        nid = next((v["note"]["id"] for v in va if isinstance(v, dict) and "note" in v), None)
        e["_note_id"] = nid
        if nid:
            (lead_note_ids if e.get("entity_type") == "lead" else contact_note_ids).append(nid)

    contact_notes = fetch_notes_batch("contact", contact_note_ids) if contact_note_ids else {}
    lead_notes    = fetch_notes_batch("lead",    lead_note_ids)    if lead_note_ids    else {}

    mgr_calls_cnt = defaultdict(int)
    mgr_connected = defaultdict(int)
    mgr_seconds   = defaultdict(int)
    for e in mgr_calls_raw:
        uid = e["created_by"]
        nid = e.get("_note_id")
        params = {}
        if nid:
            params = (lead_notes if e.get("entity_type") == "lead" else contact_notes).get(nid, {})
        dur = params.get("duration", 0) or 0
        mgr_calls_cnt[uid] += 1
        if dur > 0:
            mgr_connected[uid] += 1
            mgr_seconds[uid]   += dur

    status_events = fetch_events(["lead_status_changed"], ts_from, ts_to)

    contract_deal_ids: set = set()
    mgr_meeting_deals: dict = defaultdict(set)
    for e in status_events:
        uid     = e.get("created_by")
        deal_id = e.get("entity_id")
        for v in (e.get("value_after") or []):
            if not isinstance(v, dict):
                continue
            stage_id = (v.get("lead_status") or {}).get("id")
            if stage_id == STAGE_MEETING and uid in MANAGERS:
                mgr_meeting_deals[uid].add(deal_id)
            elif stage_id in (STAGE_PREPAY1, STAGE_FULL_PAYMENT):
                contract_deal_ids.add(deal_id)

    mgr_meetings           = {uid: len(deals) for uid, deals in mgr_meeting_deals.items()}
    mgr_contracts_meetings = {uid: len(deals & contract_deal_ids)
                               for uid, deals in mgr_meeting_deals.items()}

    payments = fetch_payments_today()

    lines = [f"📊 <b>Отчёт менеджеров Шымкент — {date_str}</b>\n"]
    for uid, name in sorted(MANAGERS.items(), key=lambda x: x[1]):
        call_min    = mgr_seconds.get(uid, 0) // 60
        meetings    = mgr_meetings.get(uid, 0)
        contracts_m = mgr_contracts_meetings.get(uid, 0)
        calls       = mgr_calls_cnt.get(uid, 0)
        connected   = mgr_connected.get(uid, 0)
        pay_sum     = payments.get(uid, 0)
        if calls == 0 and meetings == 0 and pay_sum == 0:
            continue
        formula_min = call_min + meetings * 15 + contracts_m * 5
        pct         = min(100, round(formula_min / PLAN_MIN * 100))
        bar         = progress_bar(pct)
        pay_str     = f"{pay_sum:,.0f} тг".replace(",", " ") if pay_sum else "—"
        lines.append(
            f"<b>{name}</b>\n"
            f"  📞 {call_min} мин ({calls} зв, {connected} дозвон)\n"
            f"  🤝 {meetings} встреч (+{meetings*15} мин)  |  📝 {contracts_m} дог. (+{contracts_m*5} мин)\n"
            f"  💰 Оплаты: {pay_str}\n"
            f"  Итого: <b>{formula_min}</b> / {PLAN_MIN} мин  {bar} {pct}%\n"
        )
    if len(lines) == 1:
        lines.append("Нет активности за сегодня.")

    total_calls     = sum(mgr_calls_cnt.values())
    total_connected = sum(mgr_connected.values())
    total_min       = sum(mgr_seconds.values()) // 60
    total_meetings  = sum(mgr_meetings.values())
    total_cm        = sum(mgr_contracts_meetings.values())
    total_formula   = total_min + total_meetings * 15 + total_cm * 5
    total_pay       = sum(payments.values())
    pay_total_str   = f"{total_pay:,.0f} тг".replace(",", " ")
    lines.append(
        f"\n<b>Команда:</b> {total_formula} мин | "
        f"📞 {total_calls} зв ({total_min} мин) | "
        f"🤝 {total_meetings} встреч | 📝 {total_cm} дог. со встречи | "
        f"💰 {pay_total_str}"
    )
    return "\n".join(lines)


def main():
    ts_from, ts_to = today_ts_range()
    date_str = datetime.now(ASTANA).strftime("%d.%m.%Y")
    print(f"Report: {date_str}")

    # ── 1. Calls ─────────────────────────────────────────────────────────────
    print("Fetching call events...")
    call_events = fetch_events(["incoming_call", "outgoing_call"], ts_from, ts_to)
    mgr_calls_raw = [e for e in call_events if e.get("created_by") in MANAGERS]
    print(f"  Manager call events: {len(mgr_calls_raw)}/{len(call_events)}")

    contact_note_ids, lead_note_ids = [], []
    for e in mgr_calls_raw:
        va = e.get("value_after") or []
        nid = next((v["note"]["id"] for v in va if isinstance(v, dict) and "note" in v), None)
        e["_note_id"] = nid
        if nid:
            (lead_note_ids if e.get("entity_type") == "lead" else contact_note_ids).append(nid)

    contact_notes = fetch_notes_batch("contact", contact_note_ids) if contact_note_ids else {}
    lead_notes    = fetch_notes_batch("lead",    lead_note_ids)    if lead_note_ids    else {}

    mgr_calls_cnt = defaultdict(int)
    mgr_connected = defaultdict(int)
    mgr_seconds   = defaultdict(int)

    for e in mgr_calls_raw:
        uid = e["created_by"]
        nid = e.get("_note_id")
        params = {}
        if nid:
            params = (lead_notes if e.get("entity_type") == "lead" else contact_notes).get(nid, {})
        dur = params.get("duration", 0) or 0
        mgr_calls_cnt[uid] += 1
        if dur > 0:
            mgr_connected[uid] += 1
            mgr_seconds[uid]   += dur

    # ── 2. Stage changes ─────────────────────────────────────────────────────
    print("Fetching stage change events...")
    status_events = fetch_events(["lead_status_changed"], ts_from, ts_to)
    print(f"  Stage events: {len(status_events)}")

    # Deals that reached ДОГОВОР ПОДПИСАН today — by=0 (system/automation) is fine
    contract_deal_ids: set = set()
    # manager → set of deal_ids they moved to ВСТРЕЧА СОСТОЯЛАСЬ today
    mgr_meeting_deals: dict = defaultdict(set)

    for e in status_events:
        uid     = e.get("created_by")
        deal_id = e.get("entity_id")
        va      = e.get("value_after") or []
        for v in va:
            if not isinstance(v, dict):
                continue
            stage_id = (v.get("lead_status") or {}).get("id")
            if stage_id == STAGE_MEETING and uid in MANAGERS:
                mgr_meeting_deals[uid].add(deal_id)
            elif stage_id in (STAGE_PREPAY1, STAGE_FULL_PAYMENT):
                contract_deal_ids.add(deal_id)  # regardless of who moved it

    mgr_meetings           = {uid: len(deals) for uid, deals in mgr_meeting_deals.items()}
    mgr_contracts_meetings = {uid: len(deals & contract_deal_ids)
                               for uid, deals in mgr_meeting_deals.items()}

    # ── 3. Payments from Google Sheets ────────────────────────────────────────
    print("Fetching payments from Google Sheets...")
    payments = fetch_payments_today()
    print(f"  Payments loaded: {len(payments)} managers")

    # ── 4. Build report ───────────────────────────────────────────────────────
    lines = [f"📊 <b>Отчёт менеджеров Шымкент — {date_str}</b>\n"]

    for uid, name in sorted(MANAGERS.items(), key=lambda x: x[1]):
        call_min    = mgr_seconds.get(uid, 0) // 60
        meetings    = mgr_meetings.get(uid, 0)
        contracts_m = mgr_contracts_meetings.get(uid, 0)
        calls       = mgr_calls_cnt.get(uid, 0)
        connected   = mgr_connected.get(uid, 0)
        pay_sum     = payments.get(uid, 0)

        if calls == 0 and meetings == 0 and pay_sum == 0:
            continue

        formula_min = call_min + meetings * 15 + contracts_m * 5
        pct         = min(100, round(formula_min / PLAN_MIN * 100))
        bar         = progress_bar(pct)
        pay_str     = f"{pay_sum:,.0f} тг".replace(",", " ") if pay_sum else "—"

        lines.append(
            f"<b>{name}</b>\n"
            f"  📞 {call_min} мин ({calls} зв, {connected} дозвон)\n"
            f"  🤝 {meetings} встреч (+{meetings*15} мин)  |  📝 {contracts_m} дог. со встречи (+{contracts_m*5} мин)\n"
            f"  💰 Оплаты: {pay_str}\n"
            f"  Итого: <b>{formula_min}</b> / {PLAN_MIN} мин  {bar} {pct}%\n"
        )

    if len(lines) == 1:
        lines.append("Нет активности за сегодня.")

    # Summary row
    total_calls      = sum(mgr_calls_cnt.values())
    total_connected  = sum(mgr_connected.values())
    total_min        = sum(mgr_seconds.values()) // 60
    total_meetings   = sum(mgr_meetings.values())
    total_cm         = sum(mgr_contracts_meetings.values())
    total_formula    = total_min + total_meetings * 15 + total_cm * 5
    total_pay        = sum(payments.values())
    pay_total_str    = f"{total_pay:,.0f} тг".replace(",", " ")

    lines.append(
        f"\n<b>Команда:</b> {total_formula} мин | "
        f"📞 {total_calls} зв ({total_min} мин) | "
        f"🤝 {total_meetings} встреч | 📝 {total_cm} дог. со встречи | "
        f"💰 {pay_total_str}"
    )

    report = "\n".join(lines)
    print("\n" + report)
    send_telegram(report)
    print("\nSent to Telegram.")


if __name__ == "__main__":
    main()
