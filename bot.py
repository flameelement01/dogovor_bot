import os
import re
import sys
import logging
from io import BytesIO
from datetime import date, datetime

# Make scripts/ importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scripts"))

# Load .env file if BOT_TOKEN not set in environment
if not os.getenv("BOT_TOKEN"):
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip()

from contract_generator import generate_contract as generate_from_template
import amo
import dashboard as _db
from manager_map import MANAGER_USERNAMES

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes
)

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")

IP_DATA = {
    "mahsutov": {
        "label": "ИП «Махсутов»", "full_name": "Махсутов",
        "director": "Махсутов Адиль Шынаралович",
        "notice": "KZ62UWQ04216925", "notice_date": "29 ноября 2022",
        "iin": "950713301438", "address": "г. Шымкент, пр. Кунаева 95/1",
        "bank": "АО «Kaspi Bank»", "account": "KZ07722S000020485146",
        "phone": "+7 708 287 0264",
    },
    "bilim": {
        "label": "ИП «Білім Орталығы»", "full_name": "Білім Орталығы",
        "director": "Қалдыораз Абылайхан Аққалиұлы",
        "notice": "KZ24UWQ05575415", "notice_date": "16 октября 2023",
        "iin": "960201300071", "address": "г. Шымкент, ул. Желтоксана 35",
        "bank": "АО «Kaspi Bank»", "account": "KZ97722S000030494217",
        "phone": "+7 708 287 0264",
    }
}

(
    ENTER_DEAL_ID,
    SELECT_IP,
    ENTER_PARENT_DOC_NUM,
    ENTER_PARENT_DOC_DATE,
    ENTER_MONTH_AMOUNT,
    CONFIRM,
) = range(6)


# ==================== HELPERS ====================

def number_to_words(n):
    try:
        n = int(n)
    except Exception:
        return str(n)
    if n == 0:
        return "Ноль"
    ones = ['','один','два','три','четыре','пять','шесть','семь','восемь','девять',
            'десять','одиннадцать','двенадцать','тринадцать','четырнадцать','пятнадцать',
            'шестнадцать','семнадцать','восемнадцать','девятнадцать']
    tens = ['','','двадцать','тридцать','сорок','пятьдесят',
            'шестьдесят','семьдесят','восемьдесят','девяносто']
    hundreds = ['','сто','двести','триста','четыреста','пятьсот',
                'шестьсот','семьсот','восемьсот','девятьсот']

    def chunk(num, fem=False):
        if num == 0: return ''
        parts = []
        h = num // 100
        r = num % 100
        if h: parts.append(hundreds[h])
        if r < 20:
            if r:
                w = ones[r]
                if fem and r == 1: w = 'одна'
                if fem and r == 2: w = 'две'
                parts.append(w)
        else:
            parts.append(tens[r // 10])
            o = r % 10
            if o:
                w = ones[o]
                if fem and o == 1: w = 'одна'
                if fem and o == 2: w = 'две'
                parts.append(w)
        return ' '.join(parts)

    parts = []
    millions = n // 1_000_000
    thousands = (n % 1_000_000) // 1_000
    remainder = n % 1_000
    if millions:
        w = chunk(millions)
        m = millions % 100
        s = 'миллионов' if (11<=m<=19 or m%10 in(0,5,6,7,8,9)) else ('миллион' if m%10==1 else 'миллиона')
        parts.append(f"{w} {s}")
    if thousands:
        w = chunk(thousands, True)
        m = thousands % 100
        s = 'тысяч' if (11<=m<=19 or m%10 in(0,5,6,7,8,9)) else ('тысяча' if m%10==1 else 'тысячи')
        parts.append(f"{w} {s}")
    if remainder:
        parts.append(chunk(remainder))
    r = ' '.join(parts).strip()
    return r[0].upper() + r[1:]


def fmt_amount(val):
    try:
        n = int(str(val).replace(' ','').replace(',',''))
        return f"{n:,}".replace(",", " ") + f" ({number_to_words(n)}) тенге"
    except Exception:
        return str(val)


def calc_total(month_amount, date_from, date_to):
    """Calculate total = month_amount × number of calendar months."""
    try:
        d_from = datetime.strptime(date_from, '%d.%m.%Y')
        d_to = datetime.strptime(date_to, '%d.%m.%Y')
        months = (d_to.year - d_from.year) * 12 + (d_to.month - d_from.month)
        if months < 1:
            months = 1
        return str(int(str(month_amount).replace(' ', '').replace(',', '')) * months)
    except Exception:
        return None


# ==================== STEP ROUTER ====================

async def _next_step(msg, context):
    """Check what's still missing and route to the appropriate next state."""
    d = context.user_data

    if not d.get('ip'):
        keyboard = [
            [InlineKeyboardButton("ИП «Махсутов»", callback_data="ip_mahsutov")],
            [InlineKeyboardButton("ИП «Білім Орталығы»", callback_data="ip_bilim")],
        ]
        await msg.reply_text(
            "⚠️ ИП не определён в AmoCRM. Выберите вручную:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return SELECT_IP

    if not d.get('parent_doc_num'):
        await msg.reply_text("📋 Введите *номер удостоверения родителя*:", parse_mode='Markdown')
        return ENTER_PARENT_DOC_NUM

    if not d.get('parent_doc_date'):
        await msg.reply_text(
            "📅 Введите *дату выдачи удостоверения* родителя (ДД.ММ.ГГГГ):\n\nПример: 15.03.2018",
            parse_mode='Markdown'
        )
        return ENTER_PARENT_DOC_DATE

    if not d.get('month_amount'):
        await msg.reply_text("📆 Введите *сумму в месяц* (только цифры):", parse_mode='Markdown')
        return ENTER_MONTH_AMOUNT

    return await show_confirm(msg, context)


# ==================== HANDLERS ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "👋 *Генератор договоров AIPLUS*\n\n"
        "Введите *номер сделки* из AmoCRM:",
        parse_mode='Markdown'
    )
    return ENTER_DEAL_ID


async def enter_deal_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("⚠️ Введите числовой ID сделки из AmoCRM.")
        return ENTER_DEAL_ID

    await update.message.reply_text("⏳ Загружаю данные из AmoCRM...")

    data, error = amo.fetch_deal(int(text))
    if error:
        await update.message.reply_text(f"❌ {error}\n\nПопробуйте другой номер или введите /cancel")
        return ENTER_DEAL_ID

    # Populate user_data with all fetched values (including None-valued ones)
    context.user_data.update(data)
    context.user_data['contract_date'] = date.today().strftime('%d.%m.%Y')

    # total_amount comes directly from AMO field 914027

    # Build summary of what was fetched
    d = context.user_data
    ip_label = IP_DATA.get(d.get('ip', ''), {}).get('label', '❌ не определён')
    lines = [
        "✅ *Данные из AmoCRM:*\n",
        f"🏢 ИП: {ip_label}",
        f"📄 Договор №: {d.get('contract_num') or '—'}",
        f"📚 Курс: {d.get('course') or '—'}",
        f"🗓 Период: {d.get('date_from') or '—'} — {d.get('date_to') or '—'}",
        f"🏢 Филиал: {d.get('branch') or '—'}",
        f"💰 Сумма: {fmt_amount(d['total_amount']) if d.get('total_amount') else '—'}",
        f"\n👤 Родитель: {d.get('parent_fio') or '—'}",
        f"🪪 ИИН: {d.get('parent_iin') or '—'}",
        f"📞 Тел: {d.get('parent_phone') or '—'}",
        f"\n👧 Ребёнок: {d.get('child_fio') or '—'}",
        f"🪪 ИИН: {d.get('child_iin') or '—'}",
    ]
    await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')

    return await _next_step(update.message, context)


async def select_ip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ip_key = query.data.replace("ip_", "")
    context.user_data['ip'] = ip_key
    ip = IP_DATA[ip_key]
    await query.edit_message_text(f"✅ Выбрано: *{ip['label']}*", parse_mode='Markdown')
    return await _next_step(query.message, context)


async def enter_parent_doc_num(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    context.user_data['parent_doc_num'] = val
    deal_id = int(context.user_data.get('contract_num', 0) or 0)
    amo.update_deal_contract(deal_id, doc_num=val)
    return await _next_step(update.message, context)


async def enter_parent_doc_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    if not re.match(r'^\d{2}\.\d{2}\.\d{4}$', val):
        await update.message.reply_text(
            "⚠️ Неверный формат! Введите дату в формате *ДД.ММ.ГГГГ*\n\nПример: 15.03.2018",
            parse_mode='Markdown'
        )
        return ENTER_PARENT_DOC_DATE
    context.user_data['parent_doc_date'] = val
    deal_id = int(context.user_data.get('contract_num', 0) or 0)
    amo.update_deal_contract(deal_id, doc_date_str=val)
    return await _next_step(update.message, context)


async def enter_month_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip().replace(' ', '').replace(',', '')
    if not val.isdigit():
        await update.message.reply_text("⚠️ Введите только цифры!\n\nПример: 124000")
        return ENTER_MONTH_AMOUNT
    context.user_data['month_amount'] = val
    d = context.user_data
    try:
        amo.update_deal_month(int(d.get('contract_num', 0) or 0), val)
    except Exception:
        pass
    return await _next_step(update.message, context)


async def show_confirm(msg, context):
    d = context.user_data
    ip = IP_DATA.get(d.get('ip', 'mahsutov'), IP_DATA['mahsutov'])
    disc = d.get('discount_amount', '')
    disc_line = f"\n🎁 Со скидкой: {fmt_amount(disc)}" if disc else ""
    ct = d.get('contract_type', 'regular')
    ct_label = 'Выпускные классы (5/10/11/12)' if ct == 'graduate' else 'Обычный'
    summary = (
        f"📋 *Проверьте данные:*\n\n"
        f"🏢 ИП: {ip['label']}\n"
        f"📄 №: {d.get('contract_num','—')}\n"
        f"📅 Дата: {d.get('contract_date','—')}\n"
        f"📋 Тип: {ct_label}\n"
        f"📚 Курс: {d.get('course','—')}\n"
        f"🗓 Период: {d.get('date_from','—')} — {d.get('date_to','—')}\n"
        f"🏢 Филиал: {d.get('branch','—')}\n\n"
        f"👤 Родитель: {d.get('parent_fio','—')}\n"
        f"🪪 ИИН: {d.get('parent_iin','—')}\n"
        f"📋 УД №: {d.get('parent_doc_num','—')}\n"
        f"📅 Дата выдачи: {d.get('parent_doc_date','—')}\n\n"
        f"👧 Ребёнок: {d.get('child_fio','—')}\n"
        f"🪪 ИИН: {d.get('child_iin','—')}\n\n"
        f"💰 Сумма: {fmt_amount(d.get('total_amount','0'))}\n"
        f"📆 В месяц: {fmt_amount(d.get('month_amount','0'))}"
        f"{disc_line}"
    )
    keyboard = [
        [InlineKeyboardButton("✅ Генерировать договор", callback_data="confirm_yes")],
        [InlineKeyboardButton("🔄 Начать заново", callback_data="confirm_no")],
    ]
    await msg.reply_text(summary, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return CONFIRM


async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "confirm_no":
        await query.edit_message_text("🔄 Начинаем заново. Введите /start")
        return ConversationHandler.END

    await query.edit_message_text("⏳ Генерирую договор...")
    try:
        ip_key = context.user_data.get('ip', 'mahsutov')
        template = os.path.join(os.path.dirname(__file__), f'template_{ip_key}.docx')
        docx_bytes = generate_from_template(context.user_data, template)
        d = context.user_data
        filename = f"Договор_{d.get('contract_num','бн')}_{(d.get('parent_fio') or 'клиент').split()[0]}.docx"
        await query.message.reply_document(
            document=BytesIO(docx_bytes),
            filename=filename,
            caption=f"✅ *Договор готов!* `{filename}`\n\nДля нового договора — /start",
            parse_mode='Markdown'
        )
        # Add note to AMO deal
        d = context.user_data
        try:
            deal_id = int(d.get('contract_num', 0) or 0)
            note = (
                f"✅ Договор сгенерирован {d.get('contract_date','')}\n"
                f"Клиент: {d.get('parent_fio','')} / {d.get('child_fio','')}\n"
                f"Сумма: {d.get('total_amount','')} тг | Месяц: {d.get('month_amount','')} тг"
            )
            amo.add_note(deal_id, note)
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Generation error: {e}")
        await query.message.reply_text(f"❌ Ошибка: {e}\n\nПопробуйте /start")
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Отменено. Для нового договора — /start", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


async def my_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    name = update.effective_user.full_name
    await update.message.reply_text(
        f"👤 *{name}*\n\n"
        f"Твой Telegram chat ID:\n`{chat_id}`\n\n"
        "Отправь этот ID администратору чтобы подключить автоотправку договоров.",
        parse_mode='Markdown'
    )


ADMIN_CHAT_ID = 603785864

async def otchet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_CHAT_ID:
        return
    msg = await update.message.reply_text("⏳ Загружаю данные из AMO и таблицы...")
    try:
        from daily_manager_report import build_report
        text = build_report()
        await msg.edit_text(text, parse_mode="HTML")
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")


# ── Group search: write child name or phone → bot replies with responsible manager ──

# Group chat ID where the search feature is active (0 = any group)
GROUP_CHAT_ID    = -1004443498928   # Основная группа (поиск по AMO + приём пересылок)
FORWARD_FROM_ID  = -1001519321051   # Параллельная группа (только пересылка)

FORWARD_KEYWORDS = [
    "консультац", "встреч", "пробный", "пробн",
    "на тест", "тестирован",
]


def _extract_phone(text: str):
    """Extract first phone number from text. Returns normalized string or None."""
    all_digits = re.findall(r'\d{10,}', re.sub(r'[\s\-\(\)\+]', '', text))
    if not all_digits:
        return None
    digits = all_digits[0]
    if len(digits) >= 11 and digits[0] == '8':
        digits = digits[1:]   # 87477651084 → 7477651084
    return digits


def _extract_name(text: str):
    """
    Extract student name from message.
    Pattern: first capitalized Cyrillic word (surname) + next alphabetic word (name).
    Handles both 'Фамилия Имя' and 'Фамилия имя' formats.
    """
    words = text.split()
    for i, w in enumerate(words[:-1]):
        # Surname: starts with uppercase Cyrillic, 4+ chars total
        if not re.match(r'^[А-ЯЁ][а-яёА-ЯЁ]{3,}$', w):
            continue
        next_w = words[i + 1]
        # Name: any alphabetic Cyrillic word, 3+ chars
        if re.match(r'^[а-яёА-ЯЁ]{3,}$', next_w):
            return f"{w} {next_w}"
    return None


def _extract_query(text: str):
    """
    Extract a searchable query from any message (multi-line or mixed).
    Only reacts to phone numbers or proper names (capitalized words).
    Returns (query_string, type) where type is 'phone' or 'name', or None.
    """
    phone = _extract_phone(text)
    if phone:
        return phone, 'phone'
    name = _extract_name(text)
    if name:
        return name, 'name'
    return None, None


async def chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reply with the current chat's ID (useful for configuring group search)."""
    cid = update.effective_chat.id
    await update.message.reply_text(f"Chat ID: `{cid}`", parse_mode='Markdown')


async def parallel_group_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Forward messages from parallel group to main group if they contain student name or phone."""
    msg = update.message
    if not msg or not msg.text:
        return
    if msg.chat.id != FORWARD_FROM_ID:
        return

    # Forward only if message has phone AND visit keyword
    if not _extract_phone(msg.text):
        return
    text_lower = msg.text.lower()
    if not any(kw in text_lower for kw in FORWARD_KEYWORDS):
        return

    sender = msg.from_user
    name   = f"{sender.first_name or ''} {sender.last_name or ''}".strip() if sender else "Неизвестно"

    # Search for responsible manager in AMO
    query, _ = _extract_query(msg.text)
    responsible_line = ""
    if query:
        result = _db.search_responsible(query)
        if result:
            uid      = result["uid"]
            mgr_name = result["manager_name"]
            username = MANAGER_USERNAMES.get(uid)
            mention  = username if username else mgr_name
            src      = result.get("source", "lead")
            src_icon = "📅" if src == "task" else ("🗓" if src == "date_field" else "📋")
            responsible_line = f"\n\n{src_icon} Ответственный: {mention}"

    await context.bot.send_message(
        chat_id=GROUP_CHAT_ID,
        text=f"📨 Переслано из параллельной группы\n👤 {name}:\n\n{msg.text}{responsible_line}",
    )


async def group_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Search AMO by name/phone written in group, reply with @responsible manager."""
    msg = update.message
    logger.info(f"[group_search] RAW update: msg={bool(msg)} chat_id={msg.chat.id if msg else None} type={msg.chat.type if msg else None} text={msg.text[:40] if msg and msg.text else None}")
    if not msg or not msg.text:
        return
    if msg.chat.type not in ("group", "supergroup"):
        return
    if GROUP_CHAT_ID and msg.chat.id != GROUP_CHAT_ID:
        logger.info(f"[group_search] SKIP: chat {msg.chat.id} != GROUP_CHAT_ID {GROUP_CHAT_ID}")
        return
    # Ignore bot's own messages
    if msg.from_user and msg.from_user.is_bot:
        return

    query, qtype = _extract_query(msg.text)
    logger.info(f"[group_search] chat={msg.chat.id} text={msg.text!r} query={query!r}")
    if not query:
        return

    result = _db.search_responsible(query)
    logger.info(f"[group_search] result={result}")

    # Fallback: if phone search found nothing, try name from same message
    if not result and qtype == 'phone':
        name = _extract_name(msg.text)
        if name:
            logger.info(f"[group_search] phone not found, fallback name={name!r}")
            result = _db.search_responsible(name)
            logger.info(f"[group_search] fallback result={result}")

    if not result:
        return

    uid          = result["uid"]
    mgr_name     = result["manager_name"]
    username     = MANAGER_USERNAMES.get(uid)
    mention      = username if username else mgr_name
    lead_id      = result["lead_id"]
    lead_url     = f"https://qadam.amocrm.ru/leads/detail/{lead_id}"
    contact_name = result.get("contact_name") or "—"
    source       = result.get("source", "lead")

    if source == "task":
        src_line = "📅 <b>Задача-встреча запланирована</b>"
    elif source == "date_field":
        src_line = "🗓 <b>Дата встречи указана</b>"
    else:
        stage = result.get("stage_name", "")
        src_line = f"📋 Этап: <b>{stage}</b>"

    await msg.reply_text(
        f"ID #{lead_id}\n"
        f"👤 {contact_name}\n"
        f"{src_line}\n"
        f"Ответственный: {mention}\n"
        f'<a href="{lead_url}">🔗 Открыть сделку</a>',
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ENTER_DEAL_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_deal_id)],
            SELECT_IP: [CallbackQueryHandler(select_ip, pattern="^ip_")],
            ENTER_PARENT_DOC_NUM: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_parent_doc_num)],
            ENTER_PARENT_DOC_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_parent_doc_date)],
            ENTER_MONTH_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_month_amount)],
            CONFIRM: [CallbackQueryHandler(confirm, pattern="^confirm_")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv)
    app.add_handler(CommandHandler("myid", my_id))
    app.add_handler(CommandHandler("chatid", chatid))
    app.add_handler(CommandHandler("otchet", otchet))
    # Forward meeting messages from parallel group to main group (group 0)
    app.add_handler(MessageHandler(
        filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND,
        parallel_group_forward
    ), group=0)
    # AMO search in main group — must be in group 1 so PTB doesn't skip it
    # when parallel_group_forward runs first in group 0
    app.add_handler(MessageHandler(
        filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND,
        group_search
    ), group=1)
    print("🤖 Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
