"""
Manager stats dashboard + submit form.
Formula: total = call_minutes + meetings×15 + contracts_from_meetings×5  (plan 120 min)
"""

import os, json, time, logging, requests
from datetime import datetime, timezone, timedelta
from collections import defaultdict

logger = logging.getLogger(__name__)

ASTANA   = timezone(timedelta(hours=5))
AMO_BASE = "https://qadam.amocrm.ru/api/v4"
PLAN_MIN = 120

MANAGERS = {
    9400090:  "Кудайбергенова Райхан",
    9400138:  "Калшабек Нурислам",
    9400162:  "Мухамеджан Аружан",
    13456338: "Мирхан Диас",
    13630778: "Ермаханбетова Зияда",
    13630786: "Мамадияров Рауль",
    13824610: "Байзакова Акжибек",
    13887778: "Торебек Аяжан",
    13887806: "Айнур Шынараловна",
}

STAGE_MEETING      = 46560529  # ВСТРЕЧА СОСТОЯЛАСЬ
STAGE_PREPAY1      = 59636926  # ПРЕДОПЛАТА получена №1
STAGE_FULL_PAYMENT = 33378673  # ПОЛНАЯ ОПЛАТА ПОЛУЧЕНА (клиент заплатил сразу)

# stage_id → human name (from all pipelines)
STAGE_NAMES = {
    # Новые продажи
    33378586: "Неразобранное",       47930506: "База лидов",
    33378589: "Новая заявка",        82195666: "Callback",
    48026560: "Клиент реанимирован", 81419582: "Недозвон",
    46560523: "Ответственный назначен", 46560526: "Квалификация пройдена",
    87289686: "Не пришли",           33378592: "Встреча назначена",
    33378595: "Встреча подтверждена",46560529: "Встреча состоялась",
    33378667: "Дата договора назначена", 33378670: "Договор подписан",
    59636922: "Счёт предоплаты №1",  59636926: "Предоплата получена №1",
    61672938: "Счёт предоплаты №2",  61672942: "Предоплата получена №2",
    59636930: "Счёт полной оплаты",  33378673: "Полная оплата получена",
    51167971: "Check ERP",
    # ОБУЧАЮТСЯ
    86591154: "Новый клиент создан", 85016530: "Обучаются",
    85016534: "Пауза",
    # АПСЕЙЛЫ
    85016590: "Нужно связаться",     88492434: "Оффер получен",
    85038194: "Очистка полей",       88054554: "Дата договора назначена",
    85016594: "Счёт предоплаты №1",  85016598: "Предоплата получена №1",
    85016650: "Счёт предоплаты №2",  85016654: "Предоплата получена №2",
    85016658: "Счёт полной оплаты",  85016662: "Полная оплата получена",
    # Повторные продажи
    48026131: "Повторный клиент создан", 57361902: "Клиент реанимирован",
    48480877: "Взят в работу",       48480880: "Потребность выявлена",
    48279670: "Оффер составлен",     48279673: "Оффер отправлен",
    48279784: "Встреча назначена",   48279787: "Встреча состоялась",
    48026422: "Сумма согласована",   48026386: "Дата договора назначена",
    48279676: "Дата договора согласована", 60170938: "Договор подписан",
    48026425: "Счёт предоплаты №1",  48026134: "Предоплата получена №1",
    61671774: "Счёт предоплаты №2",  61671778: "Предоплата получена №2",
    60170942: "Счёт полной оплаты",  48420226: "Полная оплата получена",
    # Олимпиада Шымкент
    84848334: "Первичный контакт",   84902086: "Callback",
    84900334: "Недозвон",            84848338: "Переговоры",
    85276446: "Записались на пробный урок", 85276450: "Пришли на пробный урок",
    85377106: "Пробный тест ЕНТ",   85377110: "Профориентация",
    84848342: "Принимают решение",
    142: "Успешно реализовано",      143: "Закрыто",
}

TG_TOKEN   = os.getenv("BOT_TOKEN", "")
TG_CHAT_ID = 603785864  # admin

GSHEETS_ID = "1ZJvry0Lsz5S3MervhngUDOZuYhS-zPCu8JDhAI4yFJE"

# Sheet tab name → AMO manager uid
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

# In-memory cache
_cache: dict = {}
_cache_ts: float = 0
CACHE_TTL = 600  # 10 min

_sheets_cache: dict = {}   # {uid: payment_sum}
_sheets_cache_ts: float = 0
SHEETS_TTL = 300  # 5 min


_FALLBACK_TOKEN = (
    "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiIsImp0aSI6ImU0NTA3NTEyMTg2ZDcxZTUyNThjYWUyODA2MGZkNmQ1"
    "OTc2NTYyMGExODYwYTg1ODY1MWMzNmFkOTdhYTg0ZDc1MjBlYzc1NjUzOGJhMjRhIn0.eyJhdWQiOiIzZDU1YWMz"
    "Ny0wOTUwLTRiZjEtYThkNy0yNGNkYzNkMTA3MjAiLCJqdGkiOiJlNDUwNzUxMjE4NmQ3MWU1MjU4Y2FlMjgwNjBm"
    "ZDZkNTk3NjU2MjBhMTg2MGE4NTg2NTFjMzZhZDk3YWE4NGQ3NTIwZWM3NTY1MzhiYTI0YSIsImlhdCI6MTc4NTM4"
    "ODUyNSwibmJmIjoxNzg1Mzg4NTI1LCJleHAiOjE5NDMxMzYwMDAsInN1YiI6IjIyNzU2MjEiLCJncmFudF90eXBl"
    "IjoiIiwiYWNjb3VudF9pZCI6MTg5NTA4NzIsImJhc2VfZG9tYWluIjoiYW1vY3JtLnJ1IiwidmVyc2lvbiI6Miwi"
    "c2NvcGVzIjpbInB1c2hfbm90aWZpY2F0aW9ucyIsImZpbGVzIiwiY3JtIiwibm90aWZpY2F0aW9ucyJdLCJoYXNo"
    "X3V1aWQiOiI5MGQ1MjM3ZS0zYjQ0LTQ3YWQtYjQ0Ni05NzAzZmUyZmU1NjkiLCJhcGlfZG9tYWluIjoiYXBpLWIu"
    "YW1vY3JtLnJ1In0.INChlbuC-n1rh6Okm0_5i3SD4KgLp9pChGRWg1mbBkc2pK5KV_fy1Bl7QqkyJSKsdHECIwaqs"
    "6IJuncnSsLmCWR2EiXZS4GoZMOlLkNN8oX6n2T1S4QrnKMKYXMhuPOT9iMysgsOX5zCGN5BQhuu8VtWS-M5mOi6ox"
    "WQ7s3VtiLYimqFUrLOhULGKUWNvXfcHY8uvbLw3SsqNgTMRkBSCkUCo3gCXV_RjRWgasGhtBL1diWfMUMi316fWJ5"
    "hRdR_FEHZTgKHaFCODKyEI_BCK0ADgzvq6fs36rHaSOq5pRtU7f-nBjYKEtbDHakCPX_d6FKfSHxrVXF598gALbXlcA"
)

def _headers():
    token = os.getenv("AMOCRM_TOKEN") or _FALLBACK_TOKEN
    return {"Authorization": f"Bearer {token}"}


def _today_range():
    now   = datetime.now(ASTANA)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end   = now.replace(hour=23, minute=59, second=59, microsecond=0)
    return int(start.timestamp()), int(end.timestamp()), now.strftime("%d.%m.%Y")


def _fetch_events(types: list, ts_from: int, ts_to: int) -> list:
    results, page = [], 1
    while True:
        params = [("limit", 250), ("page", page),
                  ("filter[created_at][from]", ts_from),
                  ("filter[created_at][to]",   ts_to)]
        for t in types:
            params.append(("filter[type][]", t))
        r = requests.get(f"{AMO_BASE}/events", headers=_headers(),
                         params=params, timeout=15)
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


def _fetch_notes_batch(entity_type: str, note_ids: list) -> dict:
    endpoint = "contacts" if entity_type == "contact" else "leads"
    result = {}
    for i in range(0, len(note_ids), 100):
        chunk = note_ids[i:i + 100]
        params = [("limit", 250)] + [("filter[id][]", nid) for nid in chunk]
        r = requests.get(f"{AMO_BASE}/{endpoint}/notes", headers=_headers(),
                         params=params, timeout=15)
        if r.status_code == 200:
            for n in r.json().get("_embedded", {}).get("notes", []):
                result[n["id"]] = n.get("params", {})
    return result


def _parse_amount(s: str) -> float:
    s = s.replace('\xa0', '').replace(' ', '').replace(' ', '').replace(',', '.')
    try:
        return float(s)
    except Exception:
        return 0.0


def fetch_payments_today(force: bool = False) -> dict:
    """Return {uid: total_payment_sum} from Google Sheets fact table."""
    global _sheets_cache, _sheets_cache_ts

    if not force and _sheets_cache and (time.time() - _sheets_cache_ts) < SHEETS_TTL:
        return _sheets_cache

    creds_json = os.getenv("GSHEETS_CREDS", "")
    if not creds_json:
        return {}

    try:
        import gspread
        from google.oauth2.service_account import Credentials

        creds_data = json.loads(creds_json)
        scopes     = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
        creds      = Credentials.from_service_account_info(creds_data, scopes=scopes)
        gc         = gspread.authorize(creds)
        sh         = gc.open_by_key(GSHEETS_ID)

        today = datetime.now(ASTANA).strftime("%d.%m.%Y")
        result = {}
        for tab_name, uid in SHEET_TABS.items():
            try:
                ws   = sh.worksheet(tab_name)
                rows = ws.get_all_values()
                total = sum(
                    _parse_amount(row[2])
                    for row in rows[1:]
                    if len(row) > 8 and row[8].strip() == today and row[2].strip()
                )
                result[uid] = total
            except Exception as e:
                print(f"[sheets] tab {tab_name}: {e}", flush=True)

        _sheets_cache    = result
        _sheets_cache_ts = time.time()
        return result
    except Exception as e:
        print(f"[sheets] error: {e}", flush=True)
        return {}


def _build_stats() -> dict:
    """Fetch today's AMO data and return per-manager stats dict."""
    global _cache, _cache_ts

    ts_from, ts_to, date_str = _today_range()

    # calls
    call_events = _fetch_events(["incoming_call", "outgoing_call"], ts_from, ts_to)
    mgr_calls   = [e for e in call_events if e.get("created_by") in MANAGERS]

    contact_nids, lead_nids = [], []
    for e in mgr_calls:
        nid = next((v["note"]["id"] for v in (e.get("value_after") or [])
                    if isinstance(v, dict) and "note" in v), None)
        e["_nid"] = nid
        if nid:
            (lead_nids if e.get("entity_type") == "lead" else contact_nids).append(nid)

    cnotes = _fetch_notes_batch("contact", contact_nids) if contact_nids else {}
    lnotes = _fetch_notes_batch("lead",    lead_nids)    if lead_nids    else {}

    calls_cnt = defaultdict(int)
    connected = defaultdict(int)
    seconds   = defaultdict(int)
    for e in mgr_calls:
        uid    = e["created_by"]
        params = (lnotes if e.get("entity_type") == "lead" else cnotes).get(e["_nid"] or -1, {})
        dur    = params.get("duration", 0) or 0
        calls_cnt[uid] += 1
        if dur > 0:
            connected[uid] += 1
            seconds[uid]   += dur

    # stage changes
    st_events = _fetch_events(["lead_status_changed"], ts_from, ts_to)

    # deals that reached ДОГОВОР ПОДПИСАН today — by=0 (system) is fine, don't filter by uid
    contract_deal_ids = set()
    # manager → set of deal_ids they moved to ВСТРЕЧА СОСТОЯЛАСЬ today
    mgr_meeting_deals = defaultdict(set)

    for e in st_events:
        uid     = e.get("created_by")
        deal_id = e.get("entity_id")
        for v in (e.get("value_after") or []):
            sid = (v.get("lead_status") or {}).get("id") if isinstance(v, dict) else None
            if sid == STAGE_MEETING and uid in MANAGERS:
                mgr_meeting_deals[uid].add(deal_id)
            elif sid in (STAGE_PREPAY1, STAGE_FULL_PAYMENT):
                contract_deal_ids.add(deal_id)  # regardless of who moved it

    mgr_cm = defaultdict(int)
    for uid, deals in mgr_meeting_deals.items():
        mgr_cm[uid] = len(deals & contract_deal_ids)

    payments = fetch_payments_today()

    result = {}
    for uid, name in MANAGERS.items():
        call_min    = seconds[uid] // 60
        meetings    = len(mgr_meeting_deals[uid])
        contracts_m = mgr_cm[uid]
        formula_min = call_min + meetings * 15 + contracts_m * 5
        pct         = min(100, round(formula_min / PLAN_MIN * 100))
        pay_sum     = payments.get(uid, 0)
        result[uid] = {
            "uid": uid, "name": name,
            "call_min": call_min, "calls": calls_cnt[uid], "connected": connected[uid],
            "meetings": meetings, "contracts_m": contracts_m,
            "formula_min": formula_min, "pct": pct,
            "payment": pay_sum,
            "date": date_str,
        }

    _cache     = result
    _cache_ts  = time.time()
    return result


def get_stats(force: bool = False) -> dict:
    if not force and _cache and (time.time() - _cache_ts) < CACHE_TTL:
        return _cache
    return _build_stats()


def get_manager_stats(uid: int, force: bool = False):
    stats = get_stats(force=force)
    return stats.get(uid)


# ── Google Sheets ────────────────────────────────────────────────────────────

def _write_to_sheets(row: dict):
    """Append submitted manager report to 'Ежедневные отчёты' tab."""
    creds_json = os.getenv("GSHEETS_CREDS", "")
    if not creds_json:
        return

    try:
        import gspread
        from google.oauth2.service_account import Credentials
        creds_data = json.loads(creds_json)
        scopes     = ["https://www.googleapis.com/auth/spreadsheets"]
        creds      = Credentials.from_service_account_info(creds_data, scopes=scopes)
        gc         = gspread.authorize(creds)
        sh         = gc.open_by_key(GSHEETS_ID)
        ws         = sh.worksheet("Ежедневные отчёты")
        ws.append_row([
            row["date"], row["name"],
            row["call_min"], row["calls"], row["connected"],
            row["meetings"], row["contracts_m"],
            row["formula_min"], row["pct"],
            row.get("payment", 0),
            row.get("comment", ""),
            datetime.now(ASTANA).strftime("%H:%M"),
        ])
    except Exception as e:
        print(f"[sheets] write error: {e}", flush=True)


def append_payment_to_sheets(deal_id: str, student_name: str, amount: int,
                              grade: str, payment_type: str, manager_name: str) -> bool:
    """Append a payment row to the manager's fact tab in Google Sheets."""
    creds_json = os.getenv("GSHEETS_CREDS", "")
    if not creds_json:
        return False

    tab_name = None
    for t in SHEET_TABS:
        if t.lower() in manager_name.lower() or manager_name.lower() in t.lower():
            tab_name = t
            break
    if not tab_name:
        print(f"[sheets] no tab for manager={manager_name!r}", flush=True)
        return False

    today = datetime.now(ASTANA).strftime("%d.%m.%Y")
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        creds_data = json.loads(creds_json)
        scopes     = ["https://www.googleapis.com/auth/spreadsheets"]
        creds      = Credentials.from_service_account_info(creds_data, scopes=scopes)
        gc         = gspread.authorize(creds)
        sh         = gc.open_by_key(GSHEETS_ID)
        ws         = sh.worksheet(tab_name)
        # Columns: ID | ФИ ребенка | Сумма | Комиссия% | Упало | Класс | Лидоруб | Тип оплаты | Дата | Менеджер
        ws.append_row([
            deal_id, student_name, amount, "", "", grade, "", payment_type, today, tab_name
        ], value_input_option="USER_ENTERED")
        print(f"[sheets] appended payment to tab={tab_name} deal={deal_id}", flush=True)
        return True
    except Exception as e:
        print(f"[sheets] payment write error: {e}", flush=True)
        return False


def _send_tg(text: str):
    if not TG_TOKEN:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception:
        pass


def handle_submit(uid: int, comment: str = "") -> dict:
    """Called when manager submits the form. Returns result dict."""
    stats = get_manager_stats(uid, force=True)
    if not stats:
        return {"ok": False, "error": "Менеджер не найден"}

    stats["comment"] = comment

    # Write to Google Sheets
    _write_to_sheets(stats)

    # Telegram notification to admin
    bar   = "▓" * round(stats["pct"] / 10) + "░" * (10 - round(stats["pct"] / 10))
    parts = [f"📋 <b>{stats['name']}</b> отправил(а) отчёт за {stats['date']}"]
    parts.append(
        f"  📞 {stats['call_min']} мин ({stats['calls']} зв, {stats['connected']} дозвон)\n"
        f"  🤝 {stats['meetings']} встреч (+{stats['meetings']*15} мин)\n"
        f"  📝 {stats['contracts_m']} договор со встречи (+{stats['contracts_m']*5} мин)\n"
        f"  <b>Итого: {stats['formula_min']} / {PLAN_MIN} мин</b>  {bar} {stats['pct']}%"
    )
    if comment:
        parts.append(f"  💬 {comment}")
    _send_tg("\n".join(parts))

    return {"ok": True, "stats": stats}


# ── HTML pages ────────────────────────────────────────────────────────────────

FORM_HTML = """\
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Дневной отчёт</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         background: #f0f2f5; min-height: 100vh; }}
  .header {{ background: #1a1a2e; color: #fff; padding: 16px 20px;
             display: flex; justify-content: space-between; align-items: center; }}
  .header h1 {{ font-size: 1.1rem; }}
  .header p  {{ font-size: .8rem; color: #aaa; margin-top: 2px; }}
  .header a  {{ color: #aaa; font-size: .8rem; text-decoration: none; }}
  .body   {{ padding: 16px; max-width: 480px; margin: 0 auto; }}
  label   {{ display: block; font-size: .85rem; color: #555; margin-bottom: 4px; margin-top: 12px; }}
  select, textarea {{ width: 100%; padding: 12px; border: 1px solid #ddd;
    border-radius: 10px; font-size: 1rem; background: #fff; }}
  textarea {{ resize: vertical; min-height: 70px; margin-top: 4px; }}
  .card {{ background: #fff; border-radius: 12px; padding: 16px; margin-top: 16px;
           box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
  .card h2 {{ font-size: .9rem; color: #888; margin-bottom: 10px; }}
  .metric {{ display: flex; justify-content: space-between; padding: 6px 0;
             border-bottom: 1px solid #f0f0f0; font-size: .95rem; }}
  .metric:last-child {{ border: none; }}
  .metric .val {{ font-weight: 700; }}
  .bar-wrap {{ background: #eee; border-radius: 6px; height: 12px; margin: 12px 0 4px; }}
  .bar      {{ height: 12px; border-radius: 6px; transition: width .5s; }}
  .pct-label {{ font-size: .8rem; color: #666; text-align: right; }}
  .formula  {{ font-size: .78rem; color: #999; margin-top: 8px; text-align: center; }}
  .btn-row  {{ display: flex; gap: 10px; margin-top: 20px; }}
  .btn      {{ flex: 1; padding: 14px; background: #4caf50; color: #fff; border: none;
               border-radius: 12px; font-size: 1rem; font-weight: 600; cursor: pointer; }}
  .btn:disabled {{ background: #aaa; }}
  .btn.sent {{ background: #2196f3; }}
  .btn-refresh {{ flex: 0 0 auto; padding: 14px 18px; background: #fff;
                  color: #555; border: 1px solid #ddd; border-radius: 12px;
                  font-size: 1rem; cursor: pointer; }}
  .btn-refresh:disabled {{ opacity: .5; }}
  .msg {{ margin-top: 12px; text-align: center; font-size: .9rem; color: #4caf50; }}
  .loading {{ color: #888; font-size: .85rem; margin-top: 10px; }}
  .skeleton {{ background: #eee; border-radius: 6px; height: 18px; margin: 8px 0; animation: pulse 1.2s infinite; }}
  @keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:.5}} }}
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>📊 Дневной отчёт — {date}</h1>
    <p>Менеджеры Шымкент · Aiplus</p>
  </div>
  <a href="/meetings">📅 Встречи</a>
</div>
<div class="body">
  <label>Выберите своё имя</label>
  <select id="mgr" onchange="loadStats()">
    <option value="">— выберите менеджера —</option>
    {options}
  </select>

  <div id="stats-block" style="display:none">
    <div class="card">
      <h2>Показатели за сегодня</h2>
      <div class="metric"><span>📞 Минут разговора</span> <span class="val" id="s-min">—</span></div>
      <div class="metric"><span>   Звонков / дозвонились</span> <span class="val" id="s-calls">—</span></div>
      <div class="metric"><span>🤝 Встречи проведены</span> <span class="val" id="s-meet">—</span></div>
      <div class="metric"><span>📝 Договора со встречи</span> <span class="val" id="s-cm">—</span></div>
      <div class="metric"><span>💰 Оплаты за день</span> <span class="val" id="s-pay">—</span></div>
      <div class="metric"><span><b>Итого (баллы)</b></span> <span class="val" id="s-total">—</span></div>
      <div class="bar-wrap"><div class="bar" id="s-bar" style="width:0%"></div></div>
      <div class="pct-label" id="s-pct"></div>
      <div class="formula">Формула: мин + встречи×15 + договор_со_встречи×5 = итого из {plan} мин</div>
    </div>

    <label>Комментарий (опционально)</label>
    <textarea id="comment" placeholder="Например: звонила в вечернее время..."></textarea>

    <div class="btn-row">
      <button class="btn" id="btn-submit" onclick="submitForm()">Отправить отчёт</button>
      <button class="btn-refresh" id="btn-refresh" onclick="loadStats(true)" title="Обновить данные из AMO">↺ Обновить</button>
    </div>
    <div class="msg" id="msg"></div>
  </div>

  <div id="loading" class="loading" style="display:none">Загрузка данных из AMO CRM...</div>
</div>

<script>
const managers = {managers_json};

function barColor(pct) {{
  if (pct >= 80) return '#4caf50';
  if (pct >= 50) return '#ff9800';
  return '#f44336';
}}

async function loadStats(forceRefresh) {{
  const sel = document.getElementById('mgr');
  const uid = sel.value;
  if (!uid) {{ document.getElementById('stats-block').style.display = 'none'; return; }}

  const refreshBtn = document.getElementById('btn-refresh');
  if (refreshBtn) refreshBtn.disabled = true;
  document.getElementById('loading').style.display = 'block';
  document.getElementById('stats-block').style.display = 'none';
  document.getElementById('msg').textContent = '';
  document.getElementById('btn-submit').disabled = false;
  document.getElementById('btn-submit').textContent = 'Отправить отчёт';
  document.getElementById('btn-submit').className = 'btn';

  try {{
    const url = '/api/stats/' + uid + (forceRefresh ? '?refresh=1' : '');
    const res = await fetch(url);
    const d   = await res.json();
    document.getElementById('s-min').textContent   = d.call_min + ' мин';
    document.getElementById('s-calls').textContent = d.calls + ' / ' + d.connected;
    document.getElementById('s-meet').textContent  = d.meetings + ' (+' + (d.meetings*15) + ' мин)';
    document.getElementById('s-cm').textContent    = d.contracts_m + ' (+' + (d.contracts_m*5) + ' мин)';
    document.getElementById('s-pay').textContent   = d.payment ? Number(d.payment).toLocaleString('ru-RU') + ' тг' : '—';
    document.getElementById('s-total').textContent = d.formula_min + ' / {plan} мин';
    const bar = document.getElementById('s-bar');
    bar.style.width      = d.pct + '%';
    bar.style.background = barColor(d.pct);
    document.getElementById('s-pct').textContent = d.pct + '% выполнения плана';
    document.getElementById('stats-block').style.display = 'block';
  }} catch(e) {{
    document.getElementById('msg').textContent = 'Ошибка загрузки данных';
  }} finally {{
    document.getElementById('loading').style.display = 'none';
    if (refreshBtn) refreshBtn.disabled = false;
  }}
}}

async function submitForm() {{
  const uid     = document.getElementById('mgr').value;
  const comment = document.getElementById('comment').value;
  if (!uid) return;

  const btn = document.getElementById('btn-submit');
  btn.disabled = true;
  btn.textContent = 'Отправка...';

  try {{
    const res = await fetch('/api/submit', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{ uid: parseInt(uid), comment }}),
    }});
    const d = await res.json();
    if (d.ok) {{
      btn.textContent = '✅ Отправлено';
      btn.className   = 'btn sent';
      document.getElementById('msg').textContent = 'Данные отправлены в таблицу и руководителю в Telegram!';
    }} else {{
      btn.disabled = false;
      btn.textContent = 'Отправить отчёт';
      document.getElementById('msg').textContent = '❌ ' + (d.error || 'Ошибка');
    }}
  }} catch(e) {{
    btn.disabled = false;
    btn.textContent = 'Отправить отчёт';
    document.getElementById('msg').textContent = '❌ Ошибка соединения';
  }}
}}
</script>
</body>
</html>
"""


def render_form() -> str:
    date_str = datetime.now(ASTANA).strftime("%d.%m.%Y")
    options = "\n    ".join(
        f'<option value="{uid}">{name}</option>'
        for uid, name in sorted(MANAGERS.items(), key=lambda x: x[1])
    )
    mgr_json = json.dumps({str(uid): name for uid, name in MANAGERS.items()},
                           ensure_ascii=False)
    return FORM_HTML.format(
        date=date_str, options=options,
        managers_json=mgr_json, plan=PLAN_MIN,
    )


# ── Meetings page ─────────────────────────────────────────────────────────────

def fetch_meetings(uid: int, day: str = "today") -> list:
    """Return sorted list of meeting tasks (type=2) for one manager."""
    now = datetime.now(ASTANA)
    base = now if day == "today" else now + timedelta(days=1)
    d_start = base.replace(hour=0, minute=0, second=0, microsecond=0)
    d_end   = base.replace(hour=23, minute=59, second=59, microsecond=0)

    params = [
        ("limit", 250),
        ("filter[task_type][]", 2),
        ("filter[responsible_user_id][]", uid),
        ("filter[complete_till][from]", int(d_start.timestamp())),
        ("filter[complete_till][to]",   int(d_end.timestamp())),
    ]
    r = requests.get(f"{AMO_BASE}/tasks", headers=_headers(), params=params, timeout=15)
    tasks = r.json().get("_embedded", {}).get("tasks", []) if r.status_code == 200 else []

    if not tasks:
        return []

    FIELD_CHILD_FIRST = 442131  # Имя ученика
    FIELD_CHILD_LAST  = 442133  # Фамилия ученика

    # Batch fetch leads → contact IDs + child name from custom fields
    lead_ids = list({t["entity_id"] for t in tasks if t.get("entity_type") == "leads"})
    contact_of_lead = {}   # lead_id → contact_id
    child_of_lead   = {}   # lead_id → "Фамилия Имя" or ""
    for i in range(0, len(lead_ids), 50):
        chunk = lead_ids[i:i + 50]
        p2 = [("limit", 250), ("with", "contacts")] + [("filter[id][]", lid) for lid in chunk]
        r2 = requests.get(f"{AMO_BASE}/leads", headers=_headers(), params=p2, timeout=15)
        if r2.status_code == 200:
            for lead in r2.json().get("_embedded", {}).get("leads", []):
                lid = lead["id"]
                contacts = lead.get("_embedded", {}).get("contacts", [])
                main = next((c for c in contacts if c.get("is_main")), contacts[0] if contacts else None)
                if main:
                    contact_of_lead[lid] = main["id"]
                # Extract child name from custom fields
                cf = {f["field_id"]: (f["values"][0]["value"] if f.get("values") else "")
                      for f in (lead.get("custom_fields_values") or [])}
                first = str(cf.get(FIELD_CHILD_FIRST, "") or "").strip()
                last  = str(cf.get(FIELD_CHILD_LAST,  "") or "").strip()
                child_of_lead[lid] = " ".join(filter(None, [last, first]))

    # Batch fetch parent (contact) names
    cids = list(set(contact_of_lead.values()))
    parent_name = {}
    for i in range(0, len(cids), 100):
        chunk = cids[i:i + 100]
        p3 = [("limit", 250)] + [("filter[id][]", cid) for cid in chunk]
        r3 = requests.get(f"{AMO_BASE}/contacts", headers=_headers(), params=p3, timeout=15)
        if r3.status_code == 200:
            for c in r3.json().get("_embedded", {}).get("contacts", []):
                parent_name[c["id"]] = c.get("name", "—")

    result = []
    for t in tasks:
        ct = t.get("complete_till") or 0
        dt = datetime.fromtimestamp(ct, tz=ASTANA) if ct else None
        time_str = dt.strftime("%H:%M") if dt else "—"
        lead_id = t.get("entity_id") if t.get("entity_type") == "leads" else None
        cid = contact_of_lead.get(lead_id)
        result.append({
            "time":    time_str,
            "ts":      ct,
            "parent":  parent_name.get(cid, "—") if cid else "—",
            "child":   child_of_lead.get(lead_id, ""),
            "note":    (t.get("text") or "").strip(),
            "lead_id": lead_id,
        })

    result.sort(key=lambda x: x["ts"])
    return result


MEETINGS_HTML = """\
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Встречи на день</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         background: #f0f2f5; min-height: 100vh; }}
  .header {{ background: #1a1a2e; color: #fff; padding: 16px 20px;
             display: flex; justify-content: space-between; align-items: center; }}
  .header h1 {{ font-size: 1.1rem; }}
  .header a {{ color: #aaa; font-size: .8rem; text-decoration: none; }}
  .body {{ padding: 16px; max-width: 520px; margin: 0 auto; }}
  label  {{ display: block; font-size: .85rem; color: #555; margin-bottom: 4px; margin-top: 12px; }}
  select {{ width: 100%; padding: 12px; border: 1px solid #ddd;
            border-radius: 10px; font-size: 1rem; background: #fff; }}
  .tabs  {{ display: flex; gap: 8px; margin-top: 16px; }}
  .tab   {{ flex: 1; padding: 10px; text-align: center; border-radius: 10px;
            border: 1px solid #ddd; background: #fff; cursor: pointer;
            font-size: .95rem; color: #555; }}
  .tab.active {{ background: #1a1a2e; color: #fff; border-color: #1a1a2e; font-weight: 600; }}
  .card  {{ background: #fff; border-radius: 12px; margin-top: 14px;
            box-shadow: 0 1px 4px rgba(0,0,0,.08); overflow: hidden; }}
  .card-header {{ padding: 12px 16px; background: #f8f8f8;
                  border-bottom: 1px solid #eee; font-size: .85rem; color: #888; }}
  .meeting {{ display: flex; align-items: flex-start; padding: 14px 16px;
              border-bottom: 1px solid #f0f0f0; gap: 14px; }}
  .meeting:last-child {{ border: none; }}
  .time  {{ font-size: 1.1rem; font-weight: 700; color: #1a1a2e;
            min-width: 48px; padding-top: 2px; }}
  .info  {{ flex: 1; }}
  .parent {{ font-size: .85rem; color: #888; }}
  .child  {{ font-size: 1rem; font-weight: 700; margin-top: 2px; }}
  .note   {{ font-size: .8rem; color: #aaa; margin-top: 3px; }}
  .lead-link {{ font-size: .75rem; color: #2196f3; text-decoration: none; display: block; margin-top: 2px; }}
  .empty {{ padding: 40px 16px; text-align: center; color: #aaa; font-size: .9rem; }}
  .loading {{ padding: 30px; text-align: center; color: #888; font-size: .9rem; }}
  .btn-refresh {{ display: inline-block; margin-top: 14px; padding: 10px 20px;
                  background: #fff; border: 1px solid #ddd; border-radius: 10px;
                  font-size: .9rem; cursor: pointer; color: #555; }}
  .btn-refresh:disabled {{ opacity: .5; }}
  .count-badge {{ background: #e8f5e9; color: #388e3c; padding: 2px 10px;
                  border-radius: 20px; font-size: .8rem; font-weight: 600; margin-left: 8px; }}
</style>
</head>
<body>
<div class="header">
  <h1>📅 Встречи</h1>
  <a href="/form">→ Дневной отчёт</a>
</div>
<div class="body">
  <label>Выберите своё имя</label>
  <select id="mgr" onchange="loadMeetings()">
    <option value="">— выберите менеджера —</option>
    {options}
  </select>

  <div class="tabs" id="tabs" style="display:none">
    <div class="tab active" id="tab-today" onclick="switchDay('today')">Сегодня</div>
    <div class="tab"        id="tab-tomorrow" onclick="switchDay('tomorrow')">Завтра</div>
  </div>

  <div id="meetings-wrap"></div>
</div>

<script>
let currentDay = 'today';

function switchDay(day) {{
  currentDay = day;
  document.getElementById('tab-today').className    = 'tab' + (day === 'today' ? ' active' : '');
  document.getElementById('tab-tomorrow').className = 'tab' + (day === 'tomorrow' ? ' active' : '');
  loadMeetings();
}}

async function loadMeetings(forceRefresh) {{
  const uid = document.getElementById('mgr').value;
  if (!uid) {{
    document.getElementById('tabs').style.display = 'none';
    document.getElementById('meetings-wrap').innerHTML = '';
    return;
  }}

  document.getElementById('tabs').style.display = 'flex';
  document.getElementById('meetings-wrap').innerHTML = '<div class="loading">Загрузка встреч из AMO CRM...</div>';

  const url = '/api/meetings/' + uid + '?day=' + currentDay + (forceRefresh ? '&refresh=1' : '');
  try {{
    const res  = await fetch(url);
    const data = await res.json();
    renderMeetings(data);
  }} catch(e) {{
    document.getElementById('meetings-wrap').innerHTML = '<div class="empty">Ошибка загрузки</div>';
  }}
}}

function renderMeetings(items) {{
  const label = currentDay === 'today' ? 'Сегодня' : 'Завтра';
  let html = '<div class="card">';
  html += '<div class="card-header">' + label + ' — ' + items.length + ' встреч<span class="count-badge">' + items.length + '</span></div>';

  if (items.length === 0) {{
    html += '<div class="empty">Встреч нет</div>';
  }} else {{
    items.forEach(function(m) {{
      const parentHtml = '<div class="parent">👤 ' + esc(m.parent) + '</div>';
      const childHtml  = m.child ? '<div class="child">🎓 ' + esc(m.child) + '</div>' : '';
      const noteHtml   = m.note ? '<div class="note">' + esc(m.note) + '</div>' : '';
      const linkHtml   = m.lead_id
        ? '<a class="lead-link" href="https://qadam.amocrm.ru/leads/detail/' + m.lead_id + '" target="_blank">Открыть сделку →</a>'
        : '';
      html += '<div class="meeting">' +
        '<div class="time">' + esc(m.time) + '</div>' +
        '<div class="info">' + parentHtml + childHtml + noteHtml + linkHtml + '</div>' +
        '</div>';
    }});
  }}
  html += '</div>';
  html += '<button class="btn-refresh" id="btn-ref" onclick="loadMeetings(true)">↺ Обновить</button>';
  document.getElementById('meetings-wrap').innerHTML = html;
}}

function esc(s) {{
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}}
</script>
</body>
</html>
"""


_CLOSED_STATUSES    = {142, 143}   # AMO: won / lost
_FIELD_MEETING_DATE = 875373       # Дата встречи (custom field on lead)
_PIPELINE_NEW_SALES = 3321094      # Новые продажи — highest priority


def search_responsible(query: str):
    """
    Search AMO by child name or phone.
    Priority:
      1. Active lead that has a meeting TASK (type=2) today or tomorrow
      2. Active lead with 'Дата встречи' field = today or tomorrow
      3. Any active lead (first match, Shymkent managers only)
    Returns {uid, manager_name, lead_id, contact_name, source} or None.
    """
    hdrs  = _headers()
    query = query.strip()

    now          = datetime.now(ASTANA)
    ts_start     = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    ts_end       = int((now + timedelta(days=1)).replace(hour=23, minute=59, second=59, microsecond=0).timestamp())
    today_str    = now.strftime("%d.%m.%Y")
    tomorrow_str = (now + timedelta(days=1)).strftime("%d.%m.%Y")

    # ── Step 1: search contacts AND leads simultaneously ──────────────────────
    # Contacts search: finds by parent name or phone
    r_c = requests.get(f"{AMO_BASE}/contacts", headers=hdrs,
                       params=[("query", query), ("limit", 20), ("with", "leads")],
                       timeout=12)
    contacts = r_c.json().get("_embedded", {}).get("contacts", []) if r_c.status_code == 200 else []

    # Leads search: finds by child name in custom fields (442131 имя, 442133 фам)
    r_l = requests.get(f"{AMO_BASE}/leads", headers=hdrs,
                       params=[("query", query), ("limit", 50)],
                       timeout=12)
    leads_direct = r_l.json().get("_embedded", {}).get("leads", []) if r_l.status_code == 200 else []

    lead_to_contact = {}   # lead_id → display name
    for c in contacts:
        cname = c.get("name", "—")
        for ls in (c.get("_embedded", {}).get("leads") or []):
            lead_to_contact[ls["id"]] = cname
    for lead in leads_direct:
        if lead["id"] not in lead_to_contact:
            lead_to_contact[lead["id"]] = lead.get("name", "—")

    lead_ids = list(lead_to_contact.keys())
    logger.info(f"[search] query={query!r} contacts={len(contacts)} leads_direct={len(leads_direct)} lead_ids={lead_ids[:10]}")
    if not lead_ids:
        return None

    # ── Step 2: fetch full lead data, keep only active Shymkent leads ─────────
    params = [("limit", 50)] + [("filter[id][]", lid) for lid in lead_ids[:30]]
    r3 = requests.get(f"{AMO_BASE}/leads", headers=hdrs, params=params, timeout=15)
    all_fetched = r3.json().get("_embedded", {}).get("leads", []) if r3.status_code == 200 else []
    active_shymkent = [
        lead for lead in all_fetched
        if lead.get("status_id") not in _CLOSED_STATUSES
        and lead.get("responsible_user_id") in MANAGERS
    ]
    # Prioritize "Новые продажи" pipeline over all others
    active_shymkent.sort(key=lambda l: 0 if l.get("pipeline_id") == _PIPELINE_NEW_SALES else 1)
    active = active_shymkent
    logger.info(f"[search] fetched={len(all_fetched)} active(shymkent)={len(active_shymkent)} "
                f"statuses={[l.get('status_id') for l in all_fetched[:5]]} "
                f"resp_uids={[l.get('responsible_user_id') for l in all_fetched[:5]]}")
    if not active:
        return None

    def _result(lead, source):
        uid = lead["responsible_user_id"]
        name = MANAGERS.get(uid, f"uid:{uid}")
        status_id = lead.get("status_id")
        return {"uid": uid, "manager_name": name,
                "lead_id": lead["id"],
                "contact_name": lead_to_contact.get(lead["id"], "—"),
                "source": source,
                "stage_name": STAGE_NAMES.get(status_id, f"Этап #{status_id}")}

    # ── Step 3: Priority 1 — meeting TASK today/tomorrow (batch fetch) ────────
    all_lead_ids = [l["id"] for l in active]
    task_params  = ([("limit", 250), ("filter[task_type][]", 2),
                     ("filter[complete_till][from]", ts_start),
                     ("filter[complete_till][to]",   ts_end)]
                    + [("filter[entity_id][]", lid) for lid in all_lead_ids])
    rt = requests.get(f"{AMO_BASE}/tasks", headers=hdrs, params=task_params, timeout=15)
    leads_with_task = set()
    if rt.status_code == 200:
        for t in rt.json().get("_embedded", {}).get("tasks", []):
            leads_with_task.add(t.get("entity_id"))

    for lead in active:
        if lead["id"] in leads_with_task:
            return _result(lead, "task")

    # ── Step 4: Priority 2 — "Дата встречи" field = today/tomorrow ───────────
    for lead in active:
        cf = {f["field_id"]: (f["values"][0]["value"] if f.get("values") else None)
              for f in (lead.get("custom_fields_values") or [])}
        mt = cf.get(_FIELD_MEETING_DATE)
        if mt:
            md = datetime.fromtimestamp(int(mt), tz=ASTANA).strftime("%d.%m.%Y")
            if md in (today_str, tomorrow_str):
                return _result(lead, "date_field")

    # ── Step 5: Priority 3 — first active lead ────────────────────────────────
    return _result(active[0], "lead")


def render_meetings() -> str:
    options = "\n    ".join(
        f'<option value="{uid}">{name}</option>'
        for uid, name in sorted(MANAGERS.items(), key=lambda x: x[1])
    )
    return MEETINGS_HTML.format(options=options)
