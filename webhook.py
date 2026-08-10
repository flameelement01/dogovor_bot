"""
AMO webhook server — generates contract when deal moves to "ДОГОВОР ПОДПИСАН"
in the offline Shymkent pipelines.
"""
import os
import re
import time
import requests as _requests
from datetime import date, datetime
from urllib.parse import parse_qs

import uvicorn
from fastapi import FastAPI, Request, Response

import amo
from contract_generator import generate_contract
from manager_map import MANAGER_MAP

BOT_TOKEN = os.getenv('BOT_TOKEN', '')

app = FastAPI()

# Offline Shymkent pipeline IDs
TRIGGER_PIPELINES = {3321094, 5410825, 10798670, 7315146}

# Stage IDs that trigger contract generation
TRIGGER_STATUSES = {
    33378670,   # Новые продажи           → ДОГОВОР ПОДПИСАН
    60170938,   # Повторные продажи       → ДОГОВОР ПОДПИСАН
    85016594,   # Апсейлы                → Счёт предоплаты №1
    85016650,   # Апсейлы                → Счёт предоплаты №2
    85016658,   # Апсейлы                → Счёт полной оплаты
    60913258,   # Сопровождение Индив    → СЧЕТ НА ОПЛАТУ ДЛЯ ПРЕДОПЛАТЫ №1
    61671614,   # Сопровождение Индив    → СЧЕТ НА ОПЛАТУ ДЛЯ ПРЕДОПЛАТЫ №2
    60913374,   # Сопровождение Индив    → СЧЕТ НА ОПЛАТУ ДЛЯ ПОЛНОЙ ОПЛАТЫ
}

CITY_SHYMKENT = {'шымкент', 'шимкент', 'shymkent'}


def _send_contract(tg_chat_id: int, docx_bytes: bytes, filename: str, deal_id: int):
    """Send .docx file to manager's Telegram chat via Bot API."""
    if not BOT_TOKEN or not tg_chat_id:
        return
    try:
        _requests.post(
            f'https://api.telegram.org/bot{BOT_TOKEN}/sendDocument',
            data={
                'chat_id': tg_chat_id,
                'caption': f'📄 Договор по сделке #{deal_id} готов!',
            },
            files={
                'document': (filename, docx_bytes,
                             'application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
            },
            timeout=30,
        )
    except Exception:
        pass


def _parse_raw(body: bytes) -> dict:
    """Parse URL-encoded AMO webhook body into raw key→[values] dict."""
    try:
        return parse_qs(body.decode('utf-8'), keep_blank_values=True)
    except Exception:
        return {}


def _extract_status_fields(raw: dict) -> dict:
    """Extract leads[status][0][field] → value."""
    result = {}
    for key, values in raw.items():
        m = re.search(r'leads\[status\]\[0\]\[(\w+)\]', key)
        if m:
            result[m.group(1)] = values[0] if values else ''
    return result


# In-memory debounce: deal_id → (fio, timestamp)
# Prevents sync loop: manager edits FIO → we PATCH → AMO fires update_lead → we skip (same fio, <60s)
_fio_sync_cache: dict = {}


def _extract_update_child_fio(raw: dict):
    """
    From an update_lead payload, return (deal_id, pipeline_id, child_fio_or_None).
    Looks for field FD_CHILD_FIO=914029 among updated custom fields.
    Returns None for child_fio if same value was synced within the last 60 seconds
    (prevents PATCH → update_lead → PATCH loop).
    """
    deal_id     = int((raw.get('leads[update][0][id]') or ['0'])[0] or 0)
    pipeline_id = int((raw.get('leads[update][0][pipeline_id]') or ['0'])[0] or 0)
    if not deal_id:
        return 0, 0, None

    # Find index N where leads[update][0][custom_fields][N][id] == '914029'
    child_fio = None
    for key, vals in raw.items():
        m = re.match(r'leads\[update\]\[0\]\[custom_fields\]\[(\d+)\]\[id\]$', key)
        if m and vals and str(vals[0]) == str(amo.FD_CHILD_FIO):
            idx = m.group(1)
            val_key = f'leads[update][0][custom_fields][{idx}][values][0][value]'
            fio_vals = raw.get(val_key, [])
            if fio_vals and fio_vals[0].strip():
                child_fio = fio_vals[0].strip()
            break

    if not child_fio:
        return deal_id, pipeline_id, None

    # Debounce: skip if same FIO for this deal was synced in the last 60s
    now = time.time()
    cached = _fio_sync_cache.get(deal_id)
    if cached and cached[0] == child_fio and (now - cached[1]) < 60:
        return deal_id, pipeline_id, None
    _fio_sync_cache[deal_id] = (child_fio, now)

    return deal_id, pipeline_id, child_fio


def _calc_total(month_amount, date_from, date_to):
    try:
        d_from = datetime.strptime(date_from, '%d.%m.%Y')
        d_to   = datetime.strptime(date_to,   '%d.%m.%Y')
        months = max(1, (d_to.year - d_from.year) * 12 + (d_to.month - d_from.month))
        return str(int(month_amount) * months)
    except Exception:
        return None


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/amo/webhook")
async def amo_webhook(request: Request):
    body = await request.body()
    raw = _parse_raw(body)

    # Log which event type arrived (helps with debugging)
    event_type = 'status_lead' if 'leads[status][0][id]' in raw else \
                 'update_lead' if 'leads[update][0][id]' in raw else 'unknown'
    deal_log = (raw.get('leads[status][0][id]') or raw.get('leads[update][0][id]') or ['?'])[0]
    print(f"[webhook] type={event_type} deal={deal_log} keys={sorted(k for k in raw if k.startswith('leads'))[:5]}", flush=True)

    # Route: update_lead → sync ФИО ребёнка
    if 'leads[update][0][id]' in raw:
        deal_id, pipeline_id, child_fio = _extract_update_child_fio(raw)
        if not deal_id:
            return Response("skip: no id", status_code=200)
        if pipeline_id and pipeline_id not in TRIGGER_PIPELINES:
            return Response("skip: pipeline", status_code=200)
        if child_fio:
            # Guard against stale AMO retries: verify the webhook value still matches
            # what's currently saved in AMO. If manager already corrected the field,
            # current_fio will differ and we skip to avoid overwriting the correction.
            current_fio = amo.get_child_fio(deal_id)
            if current_fio and current_fio != child_fio:
                print(f"[webhook] skip sync: stale retry deal={deal_id} webhook={child_fio!r} current={current_fio!r}", flush=True)
                return Response("skip: stale webhook", status_code=200)
            amo.sync_child_fio(deal_id, child_fio)
            return Response("synced child fio", status_code=200)
        return Response("skip: no fio change", status_code=200)

    # Route: status_lead → generate contract
    fields = _extract_status_fields(raw)

    try:
        deal_id          = int(fields.get('id', 0))
        status_id        = int(fields.get('status_id', 0))
        pipeline_id      = int(fields.get('pipeline_id', 0))
        resp_user_id     = int(fields.get('responsible_user_id', 0) or 0)
    except (ValueError, TypeError):
        return Response("skip: parse error", status_code=200)

    if not deal_id:
        return Response("skip: no deal_id", status_code=200)

    # Filter: only offline Shymkent pipelines
    if pipeline_id not in TRIGGER_PIPELINES:
        return Response("skip: pipeline", status_code=200)

    # Filter: only "ДОГОВОР ПОДПИСАН" stage
    if status_id not in TRIGGER_STATUSES:
        return Response("skip: status", status_code=200)

    # Fetch deal data from AMO
    data, error = amo.fetch_deal(deal_id)
    if error:
        amo.add_note(deal_id, f"❌ Ошибка генерации договора: {error}")
        return Response(f"amo error: {error}", status_code=200)

    # Filter by city Шымкент (check contact city field, skip if city not set)
    city = str(data.get('_contact_city') or '').strip().lower()
    if city and city not in CITY_SHYMKENT:
        return Response(f"skip: city={city}", status_code=200)

    # Check which required fields are missing
    missing = []
    if not data.get('ip'):              missing.append('ИП')
    if not data.get('parent_fio'):      missing.append('ФИО родителя')
    if not data.get('parent_iin'):      missing.append('ИИН родителя')
    if not data.get('parent_doc_num'):  missing.append('Номер удостоверения родителя')
    if not data.get('parent_doc_date'): missing.append('Дата выдачи удостоверения')
    if not data.get('child_fio'):       missing.append('ФИО ребенка')
    if not data.get('total_amount'):    missing.append('Общая сумма (без скидки)')
    if not data.get('month_amount'):    missing.append('Месяц по договору')
    if not data.get('date_from'):       missing.append('Дата начала')
    if not data.get('date_to'):         missing.append('Дата окончания')

    if missing:
        amo.add_note(deal_id,
            f"⚠️ Договор НЕ сгенерирован — не заполнены поля:\n"
            + '\n'.join(f'• {f}' for f in missing)
            + f"\n\nЗаполните в боте: /start → введите {deal_id}"
        )
        return Response("missing fields", status_code=200)

    data['contract_date'] = date.today().strftime('%d.%m.%Y')

    # Generate contract DOCX
    ip_key = data.get('ip', 'mahsutov')
    template = os.path.join(os.path.dirname(__file__), f'template_{ip_key}.docx')
    try:
        docx_bytes = generate_contract(data, template)
    except Exception as e:
        amo.add_note(deal_id, f"❌ Ошибка генерации договора: {e}")
        return Response(f"gen error: {e}", status_code=200)

    # Send contract to responsible manager via Telegram
    tg_chat_id = MANAGER_MAP.get(resp_user_id)
    parent_last = (data.get('parent_fio') or 'клиент').split()[0]
    filename = f"Договор_{deal_id}_{parent_last}.docx"
    _send_contract(tg_chat_id, docx_bytes, filename, deal_id)

    # Add success note to AMO deal
    parent = data.get('parent_fio') or ''
    child  = data.get('child_fio')  or ''
    ct     = 'Выпускной (5/10/11/12)' if data.get('contract_type') == 'graduate' else 'Обычный'
    tg_note = f"\n✅ Договор отправлен менеджеру в Telegram" if tg_chat_id else \
              f"\n📄 Получить файл .docx: бот @shymdogovor_bot → /start → {deal_id}"
    amo.add_note(deal_id,
        f"✅ Договор сгенерирован {data['contract_date']}\n"
        f"Тип: {ct}\n"
        f"Клиент: {parent} / {child}\n"
        f"Период: {data.get('date_from','')} — {data.get('date_to','')}\n"
        f"Сумма: {data.get('total_amount','')} тг | Месяц: {data.get('month_amount','')} тг"
        f"{tg_note}"
    )

    return Response("ok", status_code=200)


def start_server():
    port = int(os.getenv('PORT', 8080))
    uvicorn.run(app, host='0.0.0.0', port=port, log_level='info')


if __name__ == '__main__':
    start_server()
