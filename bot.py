import os
import re
import logging
from io import BytesIO
from datetime import date

from ocr import extract_from_pdfs

import fitz
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
        "iin": "960201300071", "address": "г. Шымкент, ул. Желтоксан 35",
        "bank": "АО «Kaspi Bank»", "account": "KZ97722S000030494217",
        "phone": "+7 708 287 0264",
    }
}

(
    SELECT_IP, UPLOAD_PARENT_PDF, UPLOAD_CHILD_PDF,
    ENTER_CONTRACT_NUM, SELECT_COURSE, ENTER_COURSE_CUSTOM,
    ENTER_DATE_FROM, ENTER_DATE_TO, SELECT_BRANCH,
    ENTER_TOTAL_AMOUNT, ENTER_MONTH_AMOUNT, ENTER_DISCOUNT_AMOUNT,
    ASK_SCHEDULE, ENTER_SCHEDULE, CONFIRM,
) = range(15)

COURSES = {
    "course_top": "ТОП школы (НИШ, БИЛ, РФМШ)",
    "course_ent": "ЕНТ",
    "course_level": "Повышение уровня знаний",
    "course_ind": "Индивидуальные уроки",
}

BRANCHES = {
    "branch_kunaeva": "пр. Кунаева 95/1",
    "branch_zheltoksana": "ул. Желтоксана 35",
    "branch_shayakhmetova": "ул. Шаяхметова 39",
}

# ==================== HELPERS ====================

def number_to_words(n):
    try:
        n = int(n)
    except:
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
    except:
        return str(val)


def parse_date(s):
    months = ['января','февраля','марта','апреля','мая','июня',
              'июля','августа','сентября','октября','ноября','декабря']
    m = re.match(r'(\d{1,2})[./](\d{1,2})[./](\d{4})', str(s))
    if m:
        d, mo, y = m.groups()
        return int(d), months[int(mo)-1], y
    return None, s, ''


def fmt_period(s):
    d, mn, y = parse_date(s)
    return f"«{d:02d}» {mn} {y}" if d else s


def fmt_date_short(s):
    m = re.match(r'(\d{1,2})[./](\d{1,2})[./](\d{4})', str(s))
    if m:
        d, mo, y = m.groups()
        return f"{int(d):02d}.{int(mo):02d}.{y}"
    return s


# ==================== DOCX ====================

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


def add_tbl_cell(cell, lines):
    cell.paragraphs[0].clear()
    for i, (txt, bold) in enumerate(lines):
        p = cell.paragraphs[0] if i == 0 else cell.add_paragraph()
        p.paragraph_format.space_after = Pt(3)
        r = p.add_run(txt)
        set_font(r, bold=bold)


def generate_contract(data):
    ip = IP_DATA[data['ip']]
    doc = Document()

    for section in doc.sections:
        section.top_margin = Cm(2)
        section.bottom_margin = Cm(2.5)
        section.left_margin = Cm(3)
        section.right_margin = Cm(1.5)

        # Footer with signature lines on every page
        footer = section.footer
        footer.is_linked_to_previous = False
        fp = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
        fp.clear()
        fp.alignment = WD_ALIGN_PARAGRAPH.LEFT
        fp.paragraph_format.space_before = Pt(4)
        # Add border line above footer
        from docx.oxml import OxmlElement as OE
        from docx.oxml.ns import qn as QN
        pPr = fp.paragraph_format._element.get_or_add_pPr()
        pBdr = OE('w:pBdr')
        top = OE('w:top')
        top.set(QN('w:val'), 'single')
        top.set(QN('w:sz'), '4')
        top.set(QN('w:space'), '1')
        top.set(QN('w:color'), '000000')
        pBdr.append(top)
        pPr.append(pBdr)
        r1 = fp.add_run('Центр: _______________________')
        r1.font.name = 'Times New Roman'
        r1.font.size = Pt(10)
        r2 = fp.add_run('					Родитель: _______________________')
        r2.font.name = 'Times New Roman'
        r2.font.size = Pt(10)

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
    paddr = data.get('parent_address', 'г. Шымкент')
    cfio = data.get('child_fio', '___')
    ciin = data.get('child_iin', '___')
    schedule = data.get('schedule', [])

    C = WD_ALIGN_PARAGRAPH.CENTER

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

    para(doc, [
        ('\t\tИндивидуальный предприниматель «', False, False),
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

    def h(text):
        para(doc, [(text, True, False)], align=C, indent=False, space_after=4)

    def s(text, bold=False):
        para(doc, [(text, bold, False)])

    def m(*parts):
        para(doc, list(parts))

    h('1. ПРЕДМЕТ ДОГОВОРА')
    m(('1.1. Центр обязуется предоставить образовательные услуги по курсу: «', False, False),
      (course, False, True),
      ('» в соответствии с образовательной программой Центра, а Родитель обязуется оплатить Услуги и принять их результат в порядке и на условиях, предусмотренных настоящим Договором и Приложением №1.', False, False))
    s(f'1.2. Период оказания Услуг: с {fmt_period(df)} г. по {fmt_period(dt)} г., если иное не согласовано Сторонами.')
    s('1.3. Период оказания Услуг может быть изменен по соглашению Сторон путем подписания Дополнительного соглашения.')
    m(('1.4. Форма обучения – групповая. Расписание занятий доводится через приложение «', False, False),
      ('Aiplus Mobile', True, False), ('».', False, False))
    s('1.5. Занятия не проводятся в официально установленные выходные и праздничные дни, а также при объявлении карантина или чрезвычайного положения.')
    m(('1.6. Услуги оказываются по адресу: Республика Казахстан, г. Шымкент, ', False, False),
      (branch, False, True), ('.', False, False))
    doc.add_paragraph()

    h('2. ПРАВА И ОБЯЗАННОСТИ СТОРОН')
    s('2.1. Центр обязуется:', bold=True)
    s('2.1.1. Организовать и обеспечить надлежащее оказание Услуг в соответствии с учебным планом, программой и расписанием занятий.')
    s('2.1.2. Обеспечить Слушателю доступ к учебным материалам, необходимым для освоения программы.')
    s('2.1.3. Размещать правила внутреннего распорядка в официальном мобильном приложении Центра «Aiplus Mobile» и/или направлять Родителям в электронном виде.')
    s('2.1.4. В случае необходимости заблаговременно (не менее чем за 3 часа до начала занятия) известить Слушателя и/или Родителя об отмене или переносе занятия посредством SMS, звонка или WhatsApp.')
    s('2.1.5. Обеспечивать конфиденциальность персональных данных Слушателя и Родителя. Подписание настоящего Договора означает согласие Родителя на обработку персональных данных в целях исполнения Договора.')
    s('2.1.6. Уведомить Родителя о пониженной эффективности или педагогической нецелесообразности продолжения обучения Слушателя.')
    s('2.2. Центр имеет право:', bold=True)
    s('2.2.1. Самостоятельно организовывать образовательный процесс: утверждать программы, определять методы обучения, осуществлять подбор и замену тренеров.')
    s('2.2.2. Заменить тренера по своему усмотрению с целью обеспечения непрерывности учебного процесса, уведомив Родителя/Слушателя.')
    s('2.2.3. Требовать соблюдения условий Договора и правил внутреннего распорядка Центра.')
    s('2.2.4. В случае причинения Слушателем ущерба имуществу Центра требовать от Родителя возмещения затрат в полном объёме.')
    s('2.2.5. Приостановить допуск Слушателя к занятиям в случае: неоплаты Услуг; нарушения дисциплины; признаков инфекционного заболевания.')
    s('2.2.6. Расторгнуть Договор в одностороннем внесудебном порядке при существенном нарушении его условий.')
    s('2.2.7. Отказать Родителю в заключении нового договора при наличии ранее допущенных существенных нарушений.')
    s('2.3. Родитель/Слушатель обязуется:', bold=True)
    s('2.3.1. Соблюдать условия Договора, правила внутреннего распорядка Центра и общепринятые нормы поведения.')
    s('2.3.2. Обеспечить посещение Слушателем занятий в соответствии с расписанием.')
    s('2.3.3. Нести ответственность за воспитание, обучение и создание необходимых условий для получения Слушателем образования.')
    s('2.3.4. Посещать родительские собрания, а также при необходимости являться в Центр по вызову администрации.')
    s('2.3.5. Возмещать причинённый по вине Слушателя или Родителя материальный ущерб имуществу Центра в полном объёме.')
    s('2.3.6. Обеспечить Слушателя необходимыми канцелярскими принадлежностями.')
    s('2.3.7. Информировать Центр о причинах отсутствия Слушателя: до 18:00 предшествующего дня (если занятие до 11:00) или не менее чем за 3 часа до занятия.')
    s('2.3.8. Своевременно производить оплату Услуг в соответствии с условиями Договора и Приложения №1.')
    s('2.3.9. Незамедлительно уведомлять Центр об изменении контактных данных (не позднее 1 рабочего дня).')
    s('2.3.10. С уважением относиться к работникам Центра, другим Слушателям и их родителям, а также к имуществу Центра.')
    s('2.3.11. Не использовать учебные материалы и методики Центра для ведения конкурентной деятельности без согласия Центра.')
    s('2.3.12. Не осуществлять без согласия Центра аудио-, фото- и видеосъёмку учебного процесса.')
    s('2.3.13. Соблюдать дисциплину, не отвлекать других Слушателей.')
    s('2.3.14. По запросу Центра сообщать идентификационный код тестируемого для проверки результатов тестирования.')
    s('2.3.15. Центр несёт ответственность за жизнь и здоровье Слушателя только в период проведения учебного занятия и только при нахождении Слушателя в учебной аудитории под контролем тренера. Вне данного периода ответственность полностью несёт Родитель.')
    s('2.3.16. Центр не несёт ответственности за травмы и несчастные случаи вследствие самостоятельного передвижения Слушателя вне аудитории или нарушения дисциплины.')
    s('2.3.17. Незамедлительно, но не позднее 1 (одного) рабочего дня, информировать Центр об изменении контактных данных.')
    s('2.3.18. С уважением относиться к работникам Центра, другим Слушателям и их родителям.')
    s('2.3.19. Своевременно производить оплату Услуг Центра в соответствии с условиями Договора и Приложения №1.')
    s('2.3.20. По запросу Центра сообщать идентификационный код тестируемого для проверки результатов тестирования или поступления в специализированные школы.')
    s('2.4. Родитель/Слушатель имеет право:', bold=True)
    s('2.4.1. На получение достоверной и полной информации о программе обучения и успеваемости Слушателя.')
    s('2.4.2. Свободно выражать собственные мнения и предложения в корректной форме.')
    s('2.4.3. Пользоваться имуществом Центра, необходимым для получения Услуг, в установленном порядке.')
    s('2.4.4. Требовать от Центра надлежащего оказания Услуг в соответствии с условиями Договора.')
    s('2.4.5. При наличии претензий обращаться к администрации Центра в устной или письменной форме.')
    s('2.4.6. При наступлении форс-мажора инициировать приостановление обучения на основании письменного заявления.')
    doc.add_paragraph()

    h('3. СТОИМОСТЬ УСЛУГ И ПОРЯДОК РАСЧЕТОВ')
    s('3.1. Стоимость Услуг, порядок и график оплаты за весь период обучения устанавливаются в Спецификации (Приложение №1 к настоящему Договору).')
    s('3.2. Стоимость Услуг указана без НДС, поскольку Центр не является плательщиком НДС.')
    s('3.3. Центр вправе изменять цены на будущие периоды обучения. Изменение не распространяется на уже оплаченные периоды.')
    s('3.4. В случае если предоплата произведена, но Слушатель не приступил к занятиям по причинам, не зависящим от Центра, предоплата в размере до 25 000 тенге является невозвратной.')
    s('3.5. Оплата Услуг может производиться: перечислением на расчётный счёт Центра; через платёжные терминалы и электронные платёжные системы; внесением наличных в кассу Центра с выдачей подтверждающего документа.')
    s('3.6. В случае невозможности оказания Услуг в полном объёме Центр возвращает стоимость неоказанных Услуг за вычетом фактически понесённых расходов.')
    s('3.7. Неявка Слушателя на занятия без уважительных причин не влечёт уменьшение стоимости Услуг и возврат денежных средств.')
    s('3.8. Настоящий Договор не является актом оказанных услуг. При отсутствии письменных претензий в течение 5 рабочих дней с момента окончания периода оказания Услуг — Услуги считаются принятыми Родителем.')
    doc.add_paragraph()

    h('4. СРОК ДЕЙСТВИЯ ДОГОВОРА.\nПОРЯДОК РАСТОРЖЕНИЯ И ВОЗВРАТА СТОИМОСТИ')
    s('4.1. Договор вступает в силу с даты подписания и действует до окончания периода оказания Услуг, указанного в п.1.2 и Приложении №1, а в части взаиморасчётов — до полного исполнения финансовых обязательств.')
    s('4.2. Срок действия Договора может быть продлён по соглашению Сторон путём подписания Дополнительного соглашения.')
    s('4.3. Любая из Сторон вправе расторгнуть Договор досрочно, направив письменное уведомление не менее чем за 30 календарных дней до предполагаемой даты расторжения.')
    s('4.4. При расторжении по инициативе Родителя возврат осуществляется только за неоказанные Услуги.')
    m(('4.5. Формула возврата: ', False, False), ('В = Б – (О / 30 × Ф)', True, False),
      (', где О – стоимость месяца; Б – оплаченная сумма; Ф – прошедшие дни; В – сумма к возврату. Условная продолжительность месяца — 30 календарных дней.', False, False))
    s('4.6. Возврат производится в течение 30 календарных дней с даты получения письменного заявления Родителя.')
    s('4.7. Центр вправе расторгнуть Договор в одностороннем порядке, уведомив Родителя не менее чем за 7 календарных дней.')
    doc.add_paragraph()

    h('5. ОБСТОЯТЕЛЬСТВА НЕПРЕОДОЛИМОЙ СИЛЫ (ФОРС-МАЖОР)')
    s('5.1. Стороны освобождаются от ответственности за неисполнение обязательств вследствие форс-мажора (стихийные бедствия, военные действия, решения госорганов, эпидемии, карантин, чрезвычайное положение и др.).')
    s('5.2. Исполнение обязательств Сторонами переносится на срок действия форс-мажорных обстоятельств.')
    s('5.3. Сторона, для которой наступили форс-мажорные обстоятельства, обязана уведомить другую Сторону в разумный срок.')
    s('5.4. Если форс-мажор продолжается более 6 месяцев, любая из Сторон вправе расторгнуть Договор.')
    s('5.5. При введении ограничительных мер, препятствующих очным занятиям, оказание Услуг переводится в дистанционный формат.')
    s('5.6. Дистанционное обучение в период ограничительных мер является надлежащим исполнением обязательств Центра и не является основанием для снижения стоимости Услуг.')
    doc.add_paragraph()

    h('6. ОТВЕТСТВЕННОСТЬ СТОРОН')
    s('6.1. Стороны несут ответственность в соответствии с законодательством Республики Казахстан.')
    s('6.2. За нарушение интеллектуальных прав Центра предусмотрена неустойка (штраф) до 1 000 000 (один миллион) тенге.')
    s('6.3. Центр не несёт ответственности за утерю личных вещей Слушателя, оставленных без присмотра.')
    s('6.4. При просрочке оплаты — пеня 0,1% от суммы задолженности за каждый день, но не более 10% от суммы долга.')
    s('6.5. При просрочке более 10 дней Центр вправе приостановить допуск Слушателя к занятиям.')
    s('6.6. При просрочке более 1 месяца Центр вправе расторгнуть Договор в одностороннем порядке.')
    s('6.7. В случае причинения вреда имуществу, жизни или здоровью работников Центра действиями Слушателя или Родителя — Родитель обязан возместить ущерб в полном объёме.')
    doc.add_paragraph()

    h('7. УВЕДОМЛЕНИЯ И ПЕРЕПИСКА')
    m(('7.1. Уведомления считаются надлежащими, если направлены по реквизитам Сторон или через приложение «', False, False),
      ('Aiplus Mobile', True, False), ('».', False, False))
    m(('7.1.1. Уведомления, размещённые в «', False, False), ('Aiplus Mobile', True, False),
      ('», считаются доставленными с момента их публикации.', False, False))
    s('7.1.2. Уведомления через WhatsApp считаются доставленными при появлении отметки «доставлено» или «прочитано».')
    s('7.1.3. Уведомления заказным письмом считаются доставленными на 3-й рабочий день с даты отправки.')
    s('7.2. Родитель несёт ответственность за актуальность контактных данных и обязан уведомлять Центр об их изменении не позднее 1 рабочего дня.')
    s('7.3. Уклонение от получения уведомлений не освобождает Родителя от ответственности.')
    s('7.4. Родитель даёт согласие на запись и обработку телефонных разговоров с Центром.')
    doc.add_paragraph()

    h('8. ПРИМЕНИМОЕ ПРАВО И ПОРЯДОК РАЗРЕШЕНИЯ СПОРОВ')
    s('8.1. Договор регулируется законодательством Республики Казахстан.')
    s('8.2. Споры Стороны стремятся разрешать путём переговоров.')
    s('8.3. При невозможности урегулирования — в судебных органах г. Шымкент.')
    doc.add_paragraph()

    h('9. ЗАКЛЮЧИТЕЛЬНЫЕ ПОЛОЖЕНИЯ')
    s('9.1. Изменения и дополнения к Договору действительны только в письменной форме, подписанной Сторонами.')
    s('9.2. Договор составлен в двух экземплярах, имеющих одинаковую юридическую силу.')
    s('9.3. Подписывая Договор, Родитель подтверждает, что ему разъяснены условия Договора и он ознакомлен с правилами Центра.')
    s('9.4. Родитель даёт согласие на фото- и видеосъёмку Слушателя в рамках учебного процесса и использование изображения в материалах Центра.')
    s('9.5. Родитель даёт согласие на обработку персональных данных в объёме, необходимом для исполнения Договора.')
    s('9.6. Родитель даёт согласие на получение от Центра информационных и рекламных сообщений.')
    doc.add_paragraph()

    h('10. РЕКВИЗИТЫ И ПОДПИСИ СТОРОН.')
    tbl = doc.add_table(rows=1, cols=2)
    tbl.style = 'Table Grid'
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    for col in tbl.columns:
        for cell in col.cells:
            cell.width = Cm(8.5)

    add_tbl_cell(tbl.rows[0].cells[0], [
        (f'ИП «{ip["full_name"]}»', True),
        (f'Юр. адрес: {ip["address"]}', False),
        (f'р/с {ip["account"]}', False),
        (ip["bank"], False),
        (f'ИИН {ip["iin"]}', False),
        (f'Руководитель: {ip["director"]}', False),
        (f'Контактный номер: {ip["phone"]}', False),
        ('', False),
        ('Подпись _____________________', False),
    ])

    parent_lines = [
        ('Родитель:', True),
        (f'ФИО: {pfio}', False),
        (f'ИИН {piin}', False),
        (f'удостоверение личности № {pdoc}', False),
        (f'выдано МВД РК от «{pdoc_date}»', False),
        (f'Адрес: {paddr}', False),
    ]
    if pphone:
        parent_lines.append((f'Конт.тел.: {pphone}', False))
    parent_lines += [('', False), ('Подпись. ______________________', False)]
    add_tbl_cell(tbl.rows[0].cells[1], parent_lines)

    doc.add_paragraph()
    doc.add_paragraph()

    # APPENDIX 1
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

    freeze_text = (
        'Заморозка обучения (приостановка занятий) предоставляется при приобретении длительных пакетов обучения: '
        'при оплате курса продолжительностью 6 (шесть) месяцев — предоставляется 1 (один) месяц заморозки; '
        'при оплате курса продолжительностью 10 (десять) месяцев — предоставляется 2 (два) месяца заморозки. '
        'Оформление заморозки осуществляется исключительно через официальное мобильное приложение Центра «Aiplus Mobile». '
        'Заявления по телефону, устные просьбы или письма не принимаются. '
        'Минимальный срок одной заморозки составляет 7 (семь) календарных дней. '
        'Период заморозки автоматически продлевает срок обучения. '
        'Заморозка не предоставляется задним числом и не может быть использована для уже пропущенных занятий. '
        'Неиспользованные заморозки не компенсируются при расторжении Договора. '
        'На период заморозки Слушатель освобождается от посещения занятий и выполнения учебных заданий.'
    )

    disc_text = (
        f'В случае подписания акционного предложения:\n'
        f'— При единовременной оплате полной стоимости Услуг в размере {fmt_amount(total)}, Родитель/Слушатель оплачивает: {fmt_amount(disc)}.\n'
        f'— Акционное предложение действует только при предварительной полной оплате.\n'
        f'— Акция не суммируется с другими скидками.'
    ) if disc else 'Акция не предусмотрена.'

    rows_data = [
        ('1', 'Общая стоимость Услуг:', f'Общая стоимость полного курса обучения за период с {fmt_period(df)} г. по {fmt_period(dt)} г. составляет:\n{fmt_amount(total)}.'),
        ('2', 'Порядок оплаты Услуг:', f'Стоимость 1 (одного) календарного месяца обучения: {fmt_amount(month)}.'),
        ('3', 'Условия акционного предложения (при наличии акции):', disc_text),
        ('3', 'Способ оплаты:', 'Любым способом не противоречащий законодательству РК.'),
        ('4', 'Место оказания Услуг:', f'г. Шымкент, филиал: {branch}'),
        ('5', 'Дополнительно:', freeze_text),
    ]

    app_tbl = doc.add_table(rows=len(rows_data), cols=3)
    app_tbl.style = 'Table Grid'
    app_tbl.columns[0].width = Cm(1)
    app_tbl.columns[1].width = Cm(4)
    app_tbl.columns[2].width = Cm(12)

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

    # APPENDIX 2 — PAYMENT SCHEDULE
    if schedule:
        doc.add_paragraph()
        doc.add_paragraph()
        para(doc, [('Приложение к Договору об оказании образовательных услуг', True, False)], align=C, indent=False)
        para(doc, [(f'от {date_str}', True, False)], align=C, indent=False)
        doc.add_paragraph()
        para(doc, [('График внесения оплаты абонемента за образовательные услуги', True, False)], align=C, indent=False)
        doc.add_paragraph()

        p = doc.add_paragraph()
        r = p.add_run(f'г.Шымкент\t\t\t\t\t\t{date_str}')
        set_font(r)
        p.paragraph_format.space_after = Pt(10)

        sched_tbl = doc.add_table(rows=len(schedule) + 1, cols=4)
        sched_tbl.style = 'Table Grid'
        sched_tbl.columns[0].width = Cm(3.5)
        sched_tbl.columns[1].width = Cm(4.5)
        sched_tbl.columns[2].width = Cm(4.5)
        sched_tbl.columns[3].width = Cm(4.5)

        headers = ['Дата', 'Сумма от абонемента, подлежащая оплате', 'Сумма от абонемента, подлежащая оплате', 'Общая стоимость абонемента']
        for j, hdr in enumerate(headers):
            p = sched_tbl.rows[0].cells[j].paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r = p.add_run(hdr)
            set_font(r, bold=True)

        for i, row_data in enumerate(schedule):
            row = sched_tbl.rows[i + 1]
            r = row.cells[0].paragraphs[0].add_run(fmt_date_short(row_data.get('date', '')))
            set_font(r, bold=True)
            for j, key in enumerate(['amount1', 'amount2', 'total'], 1):
                val = row_data.get(key, '')
                if val:
                    try:
                        txt = f"{int(val):,}".replace(",", " ")
                    except:
                        txt = val
                    r = row.cells[j].paragraphs[0].add_run(txt)
                    set_font(r, bold=True)

        doc.add_paragraph()
        doc.add_paragraph()

        req_tbl2 = doc.add_table(rows=1, cols=2)
        req_tbl2.style = 'Table Grid'
        req_tbl2.alignment = WD_TABLE_ALIGNMENT.CENTER
        for col in req_tbl2.columns:
            for cell in col.cells:
                cell.width = Cm(8.5)

        add_tbl_cell(req_tbl2.rows[0].cells[0], [
            (f'ИП «{ip["full_name"]}»', True),
            (f'Юр. адрес: {ip["address"]}', False),
            (f'р/с {ip["account"]}', False),
            (ip["bank"], False),
            (f'ИИН {ip["iin"]}', False),
            (f'Руководитель: {ip["director"]}', False),
            (f'Контактный номер: {ip["phone"]}', False),
            ('', False),
            ('Подпись _____________________', False),
        ])
        add_tbl_cell(req_tbl2.rows[0].cells[1], parent_lines)

        doc.add_paragraph()
        doc.add_paragraph()
        p = doc.add_paragraph()
        r = p.add_run('Центр ___________________\t\t\t\t\tРодитель__________________')
        set_font(r)

    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()


# ==================== HANDLERS ====================

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
    if update.message.photo:
        file = await update.message.photo[-1].get_file()
        context.user_data['parent_pdf'] = bytes(await file.download_as_bytearray())
        context.user_data['parent_is_photo'] = True
    elif update.message.document:
        file = await update.message.document.get_file()
        context.user_data['parent_pdf'] = bytes(await file.download_as_bytearray())
        context.user_data['parent_is_photo'] = False
    else:
        await update.message.reply_text("⚠️ Отправьте PDF файл или фото удостоверения личности родителя.")
        return UPLOAD_PARENT_PDF
    await update.message.reply_text(
        "✅ Получено!\n\n📄 Теперь отправьте PDF или фото *документа ребёнка* (свидетельство о рождении или удостоверение).",
        parse_mode='Markdown'
    )
    return UPLOAD_CHILD_PDF


async def upload_child_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        file = await update.message.photo[-1].get_file()
        context.user_data['child_pdf'] = bytes(await file.download_as_bytearray())
        context.user_data['child_is_photo'] = True
    elif update.message.document:
        file = await update.message.document.get_file()
        context.user_data['child_pdf'] = bytes(await file.download_as_bytearray())
        context.user_data['child_is_photo'] = False
    else:
        await update.message.reply_text("⚠️ Отправьте PDF файл или фото документа ребёнка.")
        return UPLOAD_CHILD_PDF

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
            f"📅 Дата выдачи: {extracted.get('parent_doc_date', '—')}\n\n"
            f"👧 Ребёнок: {extracted.get('child_fio', '—')}\n"
            f"🪪 ИИН: {extracted.get('child_iin', '—')}\n\n"
            f"⚠️ Проверьте данные — при необходимости исправите в конце."
        )
    else:
        msg = "⚠️ Не удалось извлечь данные автоматически — заполним вручную."

    await update.message.reply_text(msg, parse_mode='Markdown')
    await update.message.reply_text("📝 Введите *номер договора* (из AmoCRM):", parse_mode='Markdown')
    return ENTER_CONTRACT_NUM


async def enter_contract_num(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['contract_num'] = update.message.text.strip()
    today = date.today().strftime('%d.%m.%Y')
    context.user_data['contract_date'] = today

    keyboard = [
        [InlineKeyboardButton("ТОП школы (НИШ, БИЛ, РФМШ)", callback_data="course_top")],
        [InlineKeyboardButton("ЕНТ", callback_data="course_ent")],
        [InlineKeyboardButton("Повышение уровня знаний", callback_data="course_level")],
        [InlineKeyboardButton("Индивидуальные уроки", callback_data="course_ind")],
        [InlineKeyboardButton("✏️ Ввести вручную", callback_data="course_custom")],
    ]
    await update.message.reply_text(
        f"✅ Дата договора: *{today}* (сегодня)\n\n📚 Выберите *курс обучения*:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return SELECT_COURSE


async def select_course(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == 'course_custom':
        await query.edit_message_text("✏️ Введите название курса вручную:")
        return ENTER_COURSE_CUSTOM
    context.user_data['course'] = COURSES[query.data]
    await query.edit_message_text(
        f"✅ Курс: *{COURSES[query.data]}*\n\n📅 Введите *дату начала* обучения (ДД.ММ.ГГГГ):",
        parse_mode='Markdown'
    )
    return ENTER_DATE_FROM


async def enter_course_custom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['course'] = update.message.text.strip()
    await update.message.reply_text("📅 Введите *дату начала* обучения (ДД.ММ.ГГГГ):", parse_mode='Markdown')
    return ENTER_DATE_FROM


async def enter_date_from(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['date_from'] = update.message.text.strip()
    await update.message.reply_text("📅 Введите *дату окончания* обучения (ДД.ММ.ГГГГ):", parse_mode='Markdown')
    return ENTER_DATE_TO


async def enter_date_to(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['date_to'] = update.message.text.strip()
    keyboard = [
        [InlineKeyboardButton("пр. Кунаева 95/1", callback_data="branch_kunaeva")],
        [InlineKeyboardButton("ул. Желтоксана 35", callback_data="branch_zheltoksana")],
        [InlineKeyboardButton("ул. Шаяхметова 39", callback_data="branch_shayakhmetova")],
    ]
    await update.message.reply_text(
        "🏢 Выберите *филиал*:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return SELECT_BRANCH


async def select_branch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['branch'] = BRANCHES[query.data]
    await query.edit_message_text(
        f"✅ Филиал: *{BRANCHES[query.data]}*\n\n💰 Введите *общую сумму* договора (только цифры):",
        parse_mode='Markdown'
    )
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
        f"✅ {fmt_amount(val)}\n\n🎁 Введите *сумму со скидкой* (цифры или *нет* если без акции):",
        parse_mode='Markdown'
    )
    return ENTER_DISCOUNT_AMOUNT


async def enter_discount_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    context.user_data['discount_amount'] = '' if val.lower() in ('нет','no','-','0') else val.replace(' ','').replace(',','')
    keyboard = [
        [InlineKeyboardButton("✅ Да, добавить график платежей", callback_data="schedule_yes")],
        [InlineKeyboardButton("❌ Нет, без графика", callback_data="schedule_no")],
    ]
    await update.message.reply_text(
        "📊 Нужен *график платежей* (Приложение 2)?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return ASK_SCHEDULE


async def ask_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "schedule_no":
        context.user_data['schedule'] = []
        await query.edit_message_text("✅ Без графика платежей.")
        return await show_confirm(query.message, context)
    else:
        context.user_data['schedule'] = []
        await query.edit_message_text(
            "📊 Введите строки графика платежей.\n\n"
            "Формат: `дата; сумма1; сумма2; итого`\n\n"
            "Примеры:\n"
            "`04.04.2026; 200000; ; `\n"
            "`06.04.2026; ; 765000; 965000`\n\n"
            "Когда закончите — напишите *готово*",
            parse_mode='Markdown'
        )
        return ENTER_SCHEDULE


async def enter_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.lower() == 'готово':
        if not context.user_data.get('schedule'):
            await update.message.reply_text("⚠️ Добавьте хотя бы одну строку или нажмите /cancel")
            return ENTER_SCHEDULE
        return await show_confirm(update.message, context)

    parts = [p.strip() for p in text.split(';')]
    if len(parts) < 2:
        await update.message.reply_text(
            "⚠️ Неверный формат. Используйте: `дата; сумма1; сумма2; итого`",
            parse_mode='Markdown'
        )
        return ENTER_SCHEDULE

    row = {
        'date': parts[0] if len(parts) > 0 else '',
        'amount1': parts[1].replace(' ','') if len(parts) > 1 and parts[1] else '',
        'amount2': parts[2].replace(' ','') if len(parts) > 2 and parts[2] else '',
        'total': parts[3].replace(' ','') if len(parts) > 3 and parts[3] else '',
    }
    context.user_data['schedule'].append(row)
    count = len(context.user_data['schedule'])
    await update.message.reply_text(
        f"✅ Строка {count} добавлена: {parts[0]}\n\nДобавьте следующую или напишите *готово*",
        parse_mode='Markdown'
    )
    return ENTER_SCHEDULE


async def show_confirm(message, context):
    d = context.user_data
    ip = IP_DATA[d.get('ip', 'mahsutov')]
    disc = d.get('discount_amount', '')
    disc_line = f"\n🎁 Скидка: {fmt_amount(disc)}" if disc else ""
    sched = d.get('schedule', [])
    sched_line = f"\n📊 График: {len(sched)} строк" if sched else "\n📊 Без графика платежей"

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
        f"📅 Дата выдачи: {d.get('parent_doc_date','—')}\n\n"
        f"👧 Ребёнок: {d.get('child_fio','—')}\n"
        f"🪪 ИИН: {d.get('child_iin','—')}\n\n"
        f"💰 Сумма: {fmt_amount(d.get('total_amount','0'))}\n"
        f"📆 В месяц: {fmt_amount(d.get('month_amount','0'))}"
        f"{disc_line}{sched_line}"
    )

    keyboard = [
        [InlineKeyboardButton("✅ Генерировать договор", callback_data="confirm_yes")],
        [InlineKeyboardButton("🔄 Начать заново", callback_data="confirm_no")],
    ]
    await message.reply_text(summary, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
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
            caption=f"✅ *Договор готов!* `{filename}`\n\nДля нового договора — /start",
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
            UPLOAD_PARENT_PDF: [
                MessageHandler(filters.Document.PDF | filters.Document.IMAGE | filters.PHOTO, upload_parent_pdf)
            ],
            UPLOAD_CHILD_PDF: [
                MessageHandler(filters.Document.PDF | filters.Document.IMAGE | filters.PHOTO, upload_child_pdf)
            ],
            ENTER_CONTRACT_NUM: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_contract_num)],
            SELECT_COURSE: [CallbackQueryHandler(select_course, pattern="^course_")],
            ENTER_COURSE_CUSTOM: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_course_custom)],
            ENTER_DATE_FROM: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_date_from)],
            ENTER_DATE_TO: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_date_to)],
            SELECT_BRANCH: [CallbackQueryHandler(select_branch, pattern="^branch_")],
            ENTER_TOTAL_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_total_amount)],
            ENTER_MONTH_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_month_amount)],
            ENTER_DISCOUNT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_discount_amount)],
            ASK_SCHEDULE: [CallbackQueryHandler(ask_schedule, pattern="^schedule_")],
            ENTER_SCHEDULE: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_schedule)],
            CONFIRM: [CallbackQueryHandler(confirm, pattern="^confirm_")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv)
    print("🤖 Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
