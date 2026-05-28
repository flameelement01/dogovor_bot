import os
import json
import re
import logging
from io import BytesIO
from ocr import extract_from_pdfs

import fitz  # PyMuPDF
import pytesseract
from PIL import Image
from docx import Document
from docx.shared import Pt, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes
)

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")

# ==================== IP DATA ====================
IP_DATA = {
    "mahsutov": {
        "label": "ИП «Махсутов»",
        "full_name": "Махсутов",
        "director": "Махсутов Адиль Шынаралович",
        "notice": "KZ62UWQ04216925",
        "notice_date": "29 ноября 2022",
        "iin": "950713301438",
        "address": "г. Шымкент, пр. Кунаева 95/1",
        "bank": "АО «Kaspi Bank»",
        "account": "KZ07722S000020485146",
        "phone": "+7 708 287 0264",
    },
    "bilim": {
        "label": "ИП «Білім Орталығы»",
        "full_name": "Білім Орталығы",
        "director": "Қалдыораз Абылайхан Аққалиұлы",
        "notice": "KZ24UWQ05575415",
        "notice_date": "16 октября 2023",
        "iin": "960201300071",
        "address": "г. Шымкент, ул. Желтоксан 35",
        "bank": "АО «Kaspi Bank»",
        "account": "KZ97722S000030494217",
        "phone": "+7 708 287 0264",
    }
}

# ==================== STATES ====================
(
    SELECT_IP, UPLOAD_PARENT_PDF, UPLOAD_CHILD_PDF,
    ENTER_CONTRACT_NUM, ENTER_CONTRACT_DATE, ENTER_COURSE,
    ENTER_DATE_FROM, ENTER_DATE_TO, ENTER_BRANCH,
    ENTER_TOTAL_AMOUNT, ENTER_MONTH_AMOUNT, ENTER_DISCOUNT_AMOUNT,
    ENTER_PARENT_PHONE, CONFIRM,
) = range(14)

# ==================== NUMBER TO WORDS ====================

def number_to_words(n):
    try:
        n = int(n)
    except:
        return str(n)
    if n == 0:
        return "Ноль"

    ones = ['', 'один', 'два', 'три', 'четыре', 'пять', 'шесть', 'семь', 'восемь', 'девять',
            'десять', 'одиннадцать', 'двенадцать', 'тринадцать', 'четырнадцать', 'пятнадцать',
            'шестнадцать', 'семнадцать', 'восемнадцать', 'девятнадцать']
    tens = ['', '', 'двадцать', 'тридцать', 'сорок', 'пятьдесят',
            'шестьдесят', 'семьдесят', 'восемьдесят', 'девяносто']
    hundreds = ['', 'сто', 'двести', 'триста', 'четыреста', 'пятьсот',
                'шестьсот', 'семьсот', 'восемьсот', 'девятьсот']

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
        n = int(val)
        return f"{n:,}".replace(",", " ") + f" ({number_to_words(n)}) тенге"
    except:
        return str(val)


def parse_date(s):
    months = ['января','февраля','марта','апреля','мая','июня',
              'июля','августа','сентября','октября','ноября','декабря']
    m = re.match(r'(\d{1,2})[./](\d{1,2})[./](\d{4})', s)
    if m:
        d, mo, y = m.groups()
        return int(d), months[int(mo)-1], y
    return None, s, ''


def fmt_period(s):
    d, mn, y = parse_date(s)
    return f"«{d:02d}» {mn} {y}" if d else s


# ==================== DOCX GENERATION ====================

def set_font(run, size=12, bold=False, underline=False):
    run.font.name = 'Times New Roman'
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.underline = underline
    rPr = run._r.get_or_add_rPr()
    rFonts = OxmlElement('w:rFonts')
    rFonts.set(qn('w:ascii'), 'Times New Roman')
    rFonts.set(qn('w:hAnsi'), 'Times New Roman')
    rFonts.set(qn('w:cs'), 'Times New Roman')
    rPr.insert(0, rFonts)


def para(doc, parts, align=WD_ALIGN_PARAGRAPH.JUSTIFY, indent=True, space_after=6):
    """Add paragraph. parts = list of (text, bold, underline) or single string"""
    p = doc.add_paragraph()
    p.alignment = align
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing = Pt(14)
    if indent:
        p.paragraph_format.first_line_indent = Cm(1.25)
    if isinstance(parts, str):
        parts = [(parts, False, False)]
    for text, bold, ul in parts:
        r = p.add_run(text)
        set_font(r, bold=bold, underline=ul)
    return p


def generate_contract(data):
    ip = IP_DATA[data['ip']]
    doc = Document()

    for section in doc.sections:
        section.top_margin = Cm(2)
        section.bottom_margin = Cm(2)
        section.left_margin = Cm(3)
        section.right_margin = Cm(1.5)

    doc.styles['Normal'].font.name = 'Times New Roman'
    doc.styles['Normal'].font.size = Pt(12)

    num = data.get('contract_num', '___')
    cdate = data.get('contract_date', '')
    day, mname, year = parse_date(cdate)
    date_str = f"«{day}» {mname} {year} г." if day else cdate

    course = data.get('course', '___')
    df = data.get('date_from', '')
    dt = data.get('date_to', '')
    branch = data.get('branch', '___')

    total = data.get('total_amount', '')
    month = data.get('month_amount', '')
    disc = data.get('discount_amount', '')

    pfio = data.get('parent_fio', '___')
    piin = data.get('parent_iin', '___')
    pdoc = data.get('parent_doc_num', '___')
    pdoc_date = data.get('parent_doc_date', '___')
    pphone = data.get('parent_phone', '')
    paddr = data.get('parent_address', '___')
    cfio = data.get('child_fio', '___')
    ciin = data.get('child_iin', '___')

    C = WD_ALIGN_PARAGRAPH.CENTER
    J = WD_ALIGN_PARAGRAPH.JUSTIFY

    # TITLE
    p = doc.add_paragraph()
    p.alignment = C
    p.paragraph_format.space_after = Pt(4)
    r = p.add_run('ДОГОВОР')
    set_font(r, size=14, bold=True)

    p = doc.add_paragraph()
    p.alignment = C
    p.paragraph_format.space_after = Pt(12)
    r = p.add_run(f'ОБ ОКАЗАНИИ ОБРАЗОВАТЕЛЬНЫХ УСЛУГ №{num}')
    set_font(r, size=14, bold=True)

    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(12)
    r = p.add_run(f'город Шымкент\t\t\t\t\t\t{date_str}')
    set_font(r)

    # INTRO
    para(doc, [
        (f'\t\tИндивидуальный предприниматель «', False, False),
        (ip['full_name'], True, False),
        ('» являющийся официальным представителем торговой марки «AIPLUS», в лице руководителя ', False, False),
        (ip['director'], True, False),
        (f', действующего на основании уведомления о начале деятельности {ip["notice"]} от «{ip["notice_date"]}» года (далее – «Центр»), с одной стороны, и гражданин(ка) Республики Казахстан ', False, False),
        (pfio, False, True), (',', False, False),
    ], indent=False)

    para(doc, [
        ('ИИН ', False, False), (piin, False, True),
        (', удостоверение личности № ', False, False), (pdoc, False, True),
        (', выдано «', False, False), (pdoc_date, False, True),
        ('» МВД РК, проживающий(ая) по адресу: ', False, False), (paddr, False, True),
        (' (далее – «Родитель»), действующий(ая) в интересах несовершеннолетнего(ей)', False, False),
    ], indent=False)

    para(doc, [('Слушатель: ', False, False), (cfio, False, True), (',', False, False)], indent=False)
    para(doc, [
        ('ИИН ', False, False), (ciin, False, True),
        (', совместно именуемые «Стороны», заключили настоящий договор о нижеследующем:', False, False),
    ], indent=False)

    doc.add_paragraph()

    # SECTIONS
    def h(text):
        para(doc, [(text, True, False)], align=C, indent=False, space_after=4)

    def s(text, bold=False):
        para(doc, [(text, bold, False)])

    def m(*parts):
        para(doc, list(parts))

    h('1. ПРЕДМЕТ ДОГОВОРА')
    m(('1.1. Центр обязуется предоставить образовательные услуги по курсу: «', False, False),
      (course, False, True),
      ('» в соответствии с образовательной программой Центра, а Родитель обязуется оплатить Услуги и принять их результат.', False, False))
    s(f'1.2. Период оказания Услуг: с {fmt_period(df)} г. по {fmt_period(dt)} г., если иное не согласовано Сторонами.')
    s('1.3. Период оказания Услуг может быть изменен по соглашению Сторон путем подписания Дополнительного соглашения.')
    m(('1.4. Форма обучения – групповая. Расписание занятий доводится через приложение «', False, False),
      ('Aiplus Mobile', True, False), ('».', False, False))
    s('1.5. Занятия не проводятся в официально установленные выходные и праздничные дни, а также при объявлении карантина или чрезвычайного положения.')
    m(('1.6. Услуги оказываются по адресу: г. Шымкент, ', False, False), (branch, False, True), ('.', False, False))

    doc.add_paragraph()
    h('2. ПРАВА И ОБЯЗАННОСТИ СТОРОН')
    s('2.1. Центр обязуется:', bold=True)
    s('2.1.1. Организовать и обеспечить надлежащее оказание Услуг в соответствии с учебным планом и расписанием.')
    s('2.1.2. Обеспечить Слушателю доступ к учебным материалам.')
    s('2.1.3. Заблаговременно уведомить Слушателя и/или Родителя об отмене или переносе занятия.')
    s('2.1.4. Обеспечивать конфиденциальность персональных данных Слушателя и Родителя.')
    s('2.2. Центр имеет право:', bold=True)
    s('2.2.1. Самостоятельно организовывать образовательный процесс: утверждать программы, определять методы обучения, осуществлять подбор и замену тренеров.')
    s('2.2.2. Требовать соблюдения условий Договора и правил внутреннего распорядка Центра.')
    s('2.2.3. Приостановить допуск Слушателя к занятиям в случае неоплаты, нарушения дисциплины или признаков инфекционного заболевания.')
    s('2.2.4. Расторгнуть Договор в одностороннем порядке при существенном нарушении его условий.')
    s('2.3. Родитель/Слушатель обязуется:', bold=True)
    s('2.3.1. Соблюдать условия Договора и правила внутреннего распорядка Центра.')
    s('2.3.2. Обеспечить посещение Слушателем занятий в соответствии с расписанием.')
    s('2.3.3. Информировать Центр о причинах отсутствия: до 18:00 предшествующего дня (если занятие до 11:00) или не менее чем за 3 часа до занятия.')
    s('2.3.4. Своевременно производить оплату Услуг в соответствии с Договором и Приложением №1.')
    s('2.3.5. Возмещать ущерб, причинённый по вине Слушателя или Родителя имуществу Центра.')
    s('2.3.6. Незамедлительно уведомлять Центр об изменении контактных данных (не позднее 1 рабочего дня).')
    s('2.4. Родитель/Слушатель имеет право:', bold=True)
    s('2.4.1. Получать достоверную информацию о программе обучения и успеваемости Слушателя.')
    s('2.4.2. При наличии претензий обращаться к администрации Центра в устной или письменной форме.')

    doc.add_paragraph()
    h('3. СТОИМОСТЬ УСЛУГ И ПОРЯДОК РАСЧЕТОВ')
    s('3.1. Стоимость Услуг, порядок и график оплаты устанавливаются в Спецификации (Приложение №1).')
    s('3.2. Стоимость Услуг указана без НДС, поскольку Центр не является плательщиком НДС.')
    s('3.3. Центр вправе изменять цены на будущие периоды обучения.')
    s('3.4. Предоплата до 25 000 тенге является невозвратной, если Слушатель не приступил к занятиям по причинам, не зависящим от Центра.')
    s('3.5. Оплата производится: перечислением на расчётный счёт; через платёжные терминалы; наличными в кассу Центра с выдачей подтверждающего документа.')
    s('3.6. Неявка Слушателя на занятия без уважительных причин не влечёт возврат денежных средств.')

    doc.add_paragraph()
    h('4. СРОК ДЕЙСТВИЯ ДОГОВОРА.\nПОРЯДОК РАСТОРЖЕНИЯ И ВОЗВРАТА СТОИМОСТИ')
    s('4.1. Договор вступает в силу с даты подписания и действует до окончания периода оказания Услуг, указанного в п.1.2 и Приложении №1.')
    s('4.2. Любая из Сторон вправе расторгнуть Договор досрочно, направив письменное уведомление не менее чем за 30 календарных дней.')
    s('4.3. При расторжении по инициативе Родителя возврат осуществляется только за неоказанные Услуги.')
    m(('4.4. Формула возврата: ', False, False), ('В = Б – (О / 30 × Ф)', True, False),
      (', где О – стоимость месяца; Б – оплаченная сумма; Ф – прошедшие дни; В – сумма к возврату.', False, False))
    s('4.5. Возврат производится в течение 30 календарных дней с даты получения письменного заявления Родителя.')
    s('4.6. Центр вправе расторгнуть Договор в одностороннем порядке, уведомив Родителя не менее чем за 7 календарных дней.')

    doc.add_paragraph()
    h('5. ОБСТОЯТЕЛЬСТВА НЕПРЕОДОЛИМОЙ СИЛЫ (ФОРС-МАЖОР)')
    s('5.1. Стороны освобождаются от ответственности за неисполнение обязательств вследствие форс-мажора (стихийные бедствия, военные действия, решения госорганов, эпидемии, карантин и др.).')
    s('5.2. При введении ограничительных мер, препятствующих очным занятиям, оказание Услуг переводится в дистанционный формат.')
    s('5.3. Если форс-мажор продолжается более 6 месяцев, любая из Сторон вправе расторгнуть Договор.')

    doc.add_paragraph()
    h('6. ОТВЕТСТВЕННОСТЬ СТОРОН')
    s('6.1. Стороны несут ответственность в соответствии с законодательством Республики Казахстан.')
    s('6.2. За нарушение интеллектуальных прав Центра предусмотрена неустойка (штраф) до 1 000 000 (один миллион) тенге.')
    s('6.3. Центр не несёт ответственности за утерю личных вещей Слушателя, оставленных без присмотра.')
    s('6.4. При просрочке оплаты – пеня 0,1% от суммы задолженности за каждый день, но не более 10% от суммы долга.')
    s('6.5. При просрочке более 10 дней Центр вправе приостановить допуск Слушателя к занятиям.')
    s('6.6. При просрочке более 1 месяца Центр вправе расторгнуть Договор в одностороннем порядке.')

    doc.add_paragraph()
    h('7. УВЕДОМЛЕНИЯ И ПЕРЕПИСКА')
    m(('7.1. Уведомления считаются надлежащими, если направлены по реквизитам Сторон или через приложение «', False, False),
      ('Aiplus Mobile', True, False), ('».', False, False))
    s('7.2. Уведомления через WhatsApp считаются доставленными при появлении отметки «доставлено» или «прочитано».')
    s('7.3. Родитель несёт ответственность за актуальность контактных данных.')

    doc.add_paragraph()
    h('8. ПРИМЕНИМОЕ ПРАВО И ПОРЯДОК РАЗРЕШЕНИЯ СПОРОВ')
    s('8.1. Договор регулируется законодательством Республики Казахстан.')
    s('8.2. Споры Стороны стремятся разрешать путём переговоров.')
    s('8.3. При невозможности — в судебных органах г. Шымкент.')

    doc.add_paragraph()
    h('9. ЗАКЛЮЧИТЕЛЬНЫЕ ПОЛОЖЕНИЯ')
    s('9.1. Изменения и дополнения к Договору действительны только в письменной форме, подписанной Сторонами.')
    s('9.2. Договор составлен в двух экземплярах, имеющих одинаковую юридическую силу.')
    s('9.3. Подписывая Договор, Родитель подтверждает, что ему разъяснены условия Договора и он ознакомлен с правилами Центра.')
    s('9.4. Родитель даёт согласие на фото- и видеосъёмку Слушателя и использование изображения в материалах Центра.')
    s('9.5. Родитель даёт согласие на обработку персональных данных в объёме, необходимом для исполнения Договора.')
    s('9.6. Родитель даёт согласие на получение от Центра информационных и рекламных сообщений.')

    doc.add_paragraph()
    h('10. РЕКВИЗИТЫ И ПОДПИСИ СТОРОН')

    # Requisites table
    tbl = doc.add_table(rows=1, cols=2)
    tbl.style = 'Table Grid'
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    for col in tbl.columns:
        for cell in col.cells:
            cell.width = Cm(8.5)

    def fill_cell(cell, lines):
        cell.paragraphs[0].clear()
        for i, (txt, bold) in enumerate(lines):
            p = cell.paragraphs[0] if i == 0 else cell.add_paragraph()
            p.paragraph_format.space_after = Pt(3)
            r = p.add_run(txt)
            set_font(r, bold=bold)

    fill_cell(tbl.rows[0].cells[0], [
        (f'ИП «{ip["full_name"]}»', True),
        (f'Юр. адрес: {ip["address"]}', False),
        (f'р/с {ip["account"]}', False),
        (ip["bank"], False),
        (f'ИИН {ip["iin"]}', False),
        (f'Руководитель: {ip["director"]}', False),
        (f'Тел.: {ip["phone"]}', False),
        ('', False),
        ('Подпись _____________________', False),
    ])

    fill_cell(tbl.rows[0].cells[1], [
        ('Родитель:', True),
        (f'ФИО: {pfio}', False),
        (f'ИИН {piin}', False),
        (f'уд. личности № {pdoc}', False),
        (f'выдано МВД РК от {pdoc_date}', False),
        (f'Адрес: {paddr}', False),
        (f'Тел.: {pphone}', False),
        ('', False),
        ('Подпись. ______________________', False),
    ])

    doc.add_paragraph()
    doc.add_paragraph()

    # ===== APPENDIX 1 =====
    para(doc, [('Приложение - 1', True, False)], align=C, indent=False)
    para(doc, [('к Договору об оказании образовательных услуг', True, False)], align=C, indent=False)
    para(doc, [(f'от {date_str}', True, False)], align=C, indent=False)
    doc.add_paragraph()
    para(doc, [('Стоимость и порядок оплаты Услуг', True, False)], align=C, indent=False)
    doc.add_paragraph()

    p = doc.add_paragraph()
    r = p.add_run(f'город Шымкент\t\t\t\t\t\t{date_str}')
    set_font(r)
    p.paragraph_format.space_after = Pt(10)

    app_tbl = doc.add_table(rows=4, cols=3)
    app_tbl.style = 'Table Grid'
    app_tbl.columns[0].width = Cm(1)
    app_tbl.columns[1].width = Cm(4)
    app_tbl.columns[2].width = Cm(12)

    rows_data = [
        ('1', 'Общая стоимость Услуг:',
         f'Стоимость полного курса за период с {fmt_period(df)} г. по {fmt_period(dt)} г. составляет:\n{fmt_amount(total)}.'),
        ('2', 'Порядок оплаты:', f'Стоимость 1 (одного) календарного месяца обучения: {fmt_amount(month)}.'),
        ('3', 'Акционное предложение:',
         (f'При единовременной оплате: {fmt_amount(disc)}.\nАкция не суммируется с другими скидками.' if disc else 'Акция не предусмотрена.')),
        ('4', 'Место оказания Услуг:', f'г. Шымкент, филиал: {branch}'),
    ]

    for i, (n_, label, val) in enumerate(rows_data):
        row = app_tbl.rows[i]
        p0 = row.cells[0].paragraphs[0]
        p0.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p0.add_run(n_)
        set_font(r)
        r1 = row.cells[1].paragraphs[0].add_run(label)
        set_font(r1)
        r2 = row.cells[2].paragraphs[0].add_run(val)
        set_font(r2)

    doc.add_paragraph()
    doc.add_paragraph()
    p = doc.add_paragraph()
    r = p.add_run('Центр ___________________\t\t\t\t\tРодитель__________________')
    set_font(r)

    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()


# ==================== BOT HANDLERS ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    keyboard = [
        [InlineKeyboardButton("ИП «Махсутов»", callback_data="ip_mahsutov")],
        [InlineKeyboardButton("ИП «Білім Орталығы»", callback_data="ip_bilim")],
    ]
    await update.message.reply_text(
        "👋 *Генератор договоров AIPLUS*\n\nВыберите ИП для договора:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return SELECT_IP


async def select_ip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ip_key = query.data.replace("ip_", "")
    context.user_data['ip'] = ip_key
    ip = IP_DATA[ip_key]
    await query.edit_message_text(
        f"✅ Выбрано: *{ip['label']}*\n\n📄 Отправьте PDF *удостоверения личности родителя*",
        parse_mode='Markdown'
    )
    return UPLOAD_PARENT_PDF


async def upload_parent_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.document:
        await update.message.reply_text("⚠️ Отправьте PDF файл удостоверения личности родителя.")
        return UPLOAD_PARENT_PDF
    file = await update.message.document.get_file()
    context.user_data['parent_pdf'] = bytes(await file.download_as_bytearray())
    await update.message.reply_text(
        "✅ Получено!\n\n📄 Теперь отправьте PDF *документа ребёнка* (свидетельство о рождении или удостоверение).",
        parse_mode='Markdown'
    )
    return UPLOAD_CHILD_PDF


async def upload_child_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.document:
        await update.message.reply_text("⚠️ Отправьте PDF файл документа ребёнка.")
        return UPLOAD_CHILD_PDF
    file = await update.message.document.get_file()
    context.user_data['child_pdf'] = bytes(await file.download_as_bytearray())

    await update.message.reply_text("⏳ Читаю документы...")

    extracted = extract_from_pdfs(
        context.user_data['parent_pdf'],
        context.user_data['child_pdf'],
        os.getenv("GOOGLE_VISION_KEY", "")
    )
    context.user_data.update(extracted)

    found = [k for k in ['parent_fio','parent_iin','parent_doc_num','child_fio','child_iin'] if extracted.get(k)]
    if found:
        msg = (
            f"✅ *Извлечено из документов:*\n\n"
            f"👤 Родитель: {extracted.get('parent_fio', '—')}\n"
            f"🪪 ИИН: {extracted.get('parent_iin', '—')}\n"
            f"📋 УД №: {extracted.get('parent_doc_num', '—')}\n"
            f"📅 Дата выдачи: {extracted.get('parent_doc_date', '—')}\n"
            f"🏠 Адрес: {extracted.get('parent_address', '—')}\n\n"
            f"👧 Ребёнок: {extracted.get('child_fio', '—')}\n"
            f"🪪 ИИН: {extracted.get('child_iin', '—')}\n\n"
            f"⚠️ Проверьте данные — при необходимости исправите в конце."
        )
    else:
        msg = "⚠️ Не удалось извлечь данные автоматически — заполним вручную ниже."

    await update.message.reply_text(msg, parse_mode='Markdown')
    await update.message.reply_text("📝 Введите *номер договора* (из AmoCRM):", parse_mode='Markdown')
    return ENTER_CONTRACT_NUM


async def enter_contract_num(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['contract_num'] = update.message.text.strip()
    await update.message.reply_text("📅 Введите *дату договора* (ДД.ММ.ГГГГ):", parse_mode='Markdown')
    return ENTER_CONTRACT_DATE


async def enter_contract_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['contract_date'] = update.message.text.strip()
    await update.message.reply_text("📚 Введите *название курса* (например: Математика):", parse_mode='Markdown')
    return ENTER_COURSE


async def enter_course(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['course'] = update.message.text.strip()
    await update.message.reply_text("📅 Введите *дату начала* обучения (ДД.ММ.ГГГГ):", parse_mode='Markdown')
    return ENTER_DATE_FROM


async def enter_date_from(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['date_from'] = update.message.text.strip()
    await update.message.reply_text("📅 Введите *дату окончания* обучения (ДД.ММ.ГГГГ):", parse_mode='Markdown')
    return ENTER_DATE_TO


async def enter_date_to(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['date_to'] = update.message.text.strip()
    await update.message.reply_text("🏢 Введите *адрес филиала*:", parse_mode='Markdown')
    return ENTER_BRANCH


async def enter_branch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['branch'] = update.message.text.strip()
    await update.message.reply_text("💰 Введите *общую сумму* договора (только цифры):", parse_mode='Markdown')
    return ENTER_TOTAL_AMOUNT


async def enter_total_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip().replace(' ', '').replace(',', '')
    context.user_data['total_amount'] = val
    await update.message.reply_text(
        f"✅ {fmt_amount(val)}\n\n💰 Введите *сумму за месяц* (только цифры):",
        parse_mode='Markdown'
    )
    return ENTER_MONTH_AMOUNT


async def enter_month_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip().replace(' ', '').replace(',', '')
    context.user_data['month_amount'] = val
    await update.message.reply_text(
        f"✅ {fmt_amount(val)}\n\n🎁 Введите *сумму со скидкой* (цифры или *нет*):",
        parse_mode='Markdown'
    )
    return ENTER_DISCOUNT_AMOUNT


async def enter_discount_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    context.user_data['discount_amount'] = '' if val.lower() in ('нет','no','-','0') else val.replace(' ','').replace(',','')
    await update.message.reply_text("📱 Введите *телефон родителя*:", parse_mode='Markdown')
    return ENTER_PARENT_PHONE


async def enter_parent_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['parent_phone'] = update.message.text.strip()
    d = context.user_data
    ip = IP_DATA[d.get('ip', 'mahsutov')]
    disc = d.get('discount_amount', '')
    disc_line = f"\n🎁 Скидка: {fmt_amount(disc)}" if disc else ""

    summary = (
        f"📋 *Проверьте данные:*\n\n"
        f"🏢 ИП: {ip['label']}\n"
        f"📄 №: {d.get('contract_num','—')}\n"
        f"📅 Дата: {d.get('contract_date','—')}\n"
        f"📚 Курс: {d.get('course','—')}\n"
        f"🗓 Период: {d.get('date_from','—')} — {d.get('date_to','—')}\n"
        f"🏢 Филиал: {d.get('branch','—')}\n\n"
        f"👤 Родитель: {d.get('parent_fio','—')}\n"
        f"🪪 ИИН: {d.get('parent_iin','—')}\n"
        f"📋 УД №: {d.get('parent_doc_num','—')}\n"
        f"📱 Тел.: {d.get('parent_phone','—')}\n\n"
        f"👧 Ребёнок: {d.get('child_fio','—')}\n"
        f"🪪 ИИН: {d.get('child_iin','—')}\n\n"
        f"💰 Сумма: {fmt_amount(d.get('total_amount','0'))}\n"
        f"📆 В месяц: {fmt_amount(d.get('month_amount','0'))}{disc_line}"
    )

    keyboard = [
        [InlineKeyboardButton("✅ Генерировать договор", callback_data="confirm_yes")],
        [InlineKeyboardButton("🔄 Начать заново", callback_data="confirm_no")],
    ]
    await update.message.reply_text(summary, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return CONFIRM


async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "confirm_no":
        await query.edit_message_text("🔄 Начинаем заново. Введите /start")
        return ConversationHandler.END

    await query.edit_message_text("⏳ Генерирую договор...")

    try:
        docx_bytes = generate_contract(context.user_data)
        d = context.user_data
        filename = f"Договор_{d.get('contract_num','бн')}_{d.get('parent_fio','клиент').split()[0]}.docx"
        await query.message.reply_document(
            document=BytesIO(docx_bytes),
            filename=filename,
            caption=f"✅ *Договор готов!* {filename}\n\nДля нового договора — /start",
            parse_mode='Markdown'
        )
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
            SELECT_IP: [CallbackQueryHandler(select_ip, pattern="^ip_")],
            UPLOAD_PARENT_PDF: [MessageHandler(filters.Document.PDF, upload_parent_pdf)],
            UPLOAD_CHILD_PDF: [MessageHandler(filters.Document.PDF, upload_child_pdf)],
            ENTER_CONTRACT_NUM: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_contract_num)],
            ENTER_CONTRACT_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_contract_date)],
            ENTER_COURSE: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_course)],
            ENTER_DATE_FROM: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_date_from)],
            ENTER_DATE_TO: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_date_to)],
            ENTER_BRANCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_branch)],
            ENTER_TOTAL_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_total_amount)],
            ENTER_MONTH_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_month_amount)],
            ENTER_DISCOUNT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_discount_amount)],
            ENTER_PARENT_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_parent_phone)],
            CONFIRM: [CallbackQueryHandler(confirm, pattern="^confirm_")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv)
    print("🤖 Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
