import os
import re
import logging
from io import BytesIO
from datetime import date, datetime

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

    # Auto-calculate total if month amount and dates are already known
    if data.get('month_amount') and data.get('date_from') and data.get('date_to'):
        total = calc_total(data['month_amount'], data['date_from'], data['date_to'])
        if total:
            context.user_data['total_amount'] = total

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
    amo.update_contact(context.user_data.get('_contact_id'), doc_num=val)
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
    amo.update_contact(context.user_data.get('_contact_id'), doc_date_str=val)
    return await _next_step(update.message, context)


async def enter_month_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip().replace(' ', '').replace(',', '')
    if not val.isdigit():
        await update.message.reply_text("⚠️ Введите только цифры!\n\nПример: 124000")
        return ENTER_MONTH_AMOUNT
    context.user_data['month_amount'] = val
    d = context.user_data
    total = calc_total(val, d.get('date_from', ''), d.get('date_to', ''))
    if total:
        context.user_data['total_amount'] = total
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
    print("🤖 Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
