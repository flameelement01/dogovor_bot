"""
HTTP server hosting both the AMO contract webhook and the Telegram bot.

The Telegram bot runs in webhook mode rather than polling: Telegram pushes
updates here, which also locks out any stray instance still running getUpdates
on the same token.
"""
import os
import re
import hashlib
from contextlib import asynccontextmanager
from datetime import date, datetime
from io import BytesIO

import uvicorn
from fastapi import FastAPI, Request, Response
from telegram import BotCommand, Update

import amo
import bot as bot_module
from contract_generator import generate_contract

TG_WEBHOOK_PATH = "/tg/webhook"
TG_SECRET = hashlib.sha256(bot_module.BOT_TOKEN.encode()).hexdigest()[:32]


def _public_base_url() -> str:
    explicit = os.getenv("WEBHOOK_BASE_URL", "").rstrip("/")
    if explicit:
        return explicit
    return f"https://{os.getenv('FLY_APP_NAME', 'dogovor-bot')}.fly.dev"


@asynccontextmanager
async def lifespan(_: FastAPI):
    tg_app = bot_module.build_application()
    await tg_app.initialize()
    await tg_app.start()
    await tg_app.bot.set_webhook(
        url=_public_base_url() + TG_WEBHOOK_PATH,
        secret_token=TG_SECRET,
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )
    await tg_app.bot.set_my_commands([
        BotCommand("zapros", "Запрос от родителя"),
        BotCommand("start", "Начать"),
        BotCommand("cancel", "Отменить"),
    ])
    app.state.tg_app = tg_app
    yield
    await tg_app.bot.delete_webhook()
    await tg_app.stop()
    await tg_app.shutdown()


app = FastAPI(lifespan=lifespan)


@app.post(TG_WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != TG_SECRET:
        return Response("forbidden", status_code=403)
    tg_app = request.app.state.tg_app
    await tg_app.process_update(Update.de_json(await request.json(), tg_app.bot))
    return Response("ok", status_code=200)

# Offline Shymkent pipeline IDs
TRIGGER_PIPELINES = {3321094, 5410825, 10798670}

# "ДОГОВОР ПОДПИСАН" stage IDs across those pipelines
TRIGGER_STATUSES = {
    33378670,   # Новые продажи      → ДОГОВОР ПОДПИСАН
    60170938,   # Повторные продажи  → дОГОВОР ПОДПИСАН
    # АПСЕЙЛЫ don't have this stage yet — add "ДОГОВОР ПОДПИСАН" stage there
    # and paste its ID here when created
}

CITY_SHYMKENT = {'шымкент', 'шимкент', 'shymkent'}


def _parse_form(form) -> dict:
    """Extract lead status fields from AMO webhook form data."""
    result = {}
    for key, value in form.items():
        m = re.search(r'leads\[status\]\[0\]\[(\w+)\]', key)
        if m:
            result[m.group(1)] = value
    return result


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
    try:
        form = await request.form()
    except Exception:
        return Response("bad request", status_code=400)

    fields = _parse_form(form)

    try:
        deal_id     = int(fields.get('id', 0))
        status_id   = int(fields.get('status_id', 0))
        pipeline_id = int(fields.get('pipeline_id', 0))
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
    if not data.get('parent_doc_num'):  missing.append('Номер удостоверения родителя')
    if not data.get('parent_doc_date'): missing.append('Дата выдачи удостоверения')
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

    # Auto-calculate total
    total = _calc_total(data['month_amount'], data['date_from'], data['date_to'])
    if total:
        data['total_amount'] = total

    data['contract_date'] = date.today().strftime('%d.%m.%Y')

    # Generate contract DOCX
    ip_key = data.get('ip', 'mahsutov')
    template = os.path.join(os.path.dirname(__file__), f'template_{ip_key}.docx')
    try:
        generate_contract(data, template)
    except Exception as e:
        amo.add_note(deal_id, f"❌ Ошибка генерации договора: {e}")
        return Response(f"gen error: {e}", status_code=200)

    # Add success note to AMO deal
    parent = data.get('parent_fio') or ''
    child  = data.get('child_fio')  or ''
    ct     = 'Выпускной (5/10/11/12)' if data.get('contract_type') == 'graduate' else 'Обычный'
    amo.add_note(deal_id,
        f"✅ Данные для договора проверены {data['contract_date']}\n"
        f"Тип: {ct}\n"
        f"Клиент: {parent} / {child}\n"
        f"Период: {data.get('date_from','')} — {data.get('date_to','')}\n"
        f"Сумма: {data.get('total_amount','')} тг | Месяц: {data.get('month_amount','')} тг\n"
        f"📄 Получить файл .docx: боте @shymdogovor_bot → /start → {deal_id}"
    )

    return Response("ok", status_code=200)


def start_server():
    port = int(os.getenv('PORT', 8080))
    uvicorn.run(app, host='0.0.0.0', port=port, log_level='info')


if __name__ == '__main__':
    start_server()
