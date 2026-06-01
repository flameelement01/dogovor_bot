"""
Contract generator based on real .docx templates.
Template structure (Mahsutov & Bilim are identical in structure):

P1:  Contract number — run1 = '____________'
P2:  Date line — run9='  '(day), run12='___'(month), run13=' 202', run14='6'(year_last)
P4:  Intro — run16=parent_fio, run18=parent_iin, run19=doc_num, run21=''(day_issued),
             run23=' ____ '(month_issued), run27=address
P5:  Child — run1=child_fio_blank, run5=child_iin_blank
P7:  Course — run2='__________________________'
P8:  Period — run1(day_from+month_from), run2(month_from+year), run3(year_last),
              run7(day_to), run9(month_to), run10(year_to)
P16: Branch — run2=', ________________________________.'
T0[0][1]: Parent requisites cell
T1[0][2]: Total amount cell — P0 dates, P1 amount+words
T1[1][2]: Month amount cell — P0run2 = amount
T1[2][2]: Discount cell — P1run2=total_ref, P2run0=disc_amount
T1[4][2]: Branch cell — run2
P153: App1 date — run0='от «____» _______ 202', run1='6', run2=' года'
P157: App1 city+date — run4='___» _______ 202', run5='6', run6=' года'
"""
import re
from io import BytesIO
from docx import Document


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


def fmt_num(val):
    try:
        n = int(str(val).replace(' ','').replace(',',''))
        return f"{n:,}".replace(",", " "), number_to_words(n), n
    except:
        return str(val), '', 0


def parse_date(s):
    months = ['января','февраля','марта','апреля','мая','июня',
              'июля','августа','сентября','октября','ноября','декабря']
    m = re.match(r'(\d{1,2})[./](\d{1,2})[./](\d{4})', str(s))
    if m:
        d, mo, y = m.groups()
        return {
            'day': d.zfill(2),
            'month_num': mo.zfill(2),
            'month_name': months[int(mo)-1],
            'year': y,
            'year_last': y[3],
        }
    return None


def set_run(run, text):
    run.text = text


def generate_contract(data, template_path):
    doc = Document(template_path)

    num = data.get('contract_num', '')
    cdate = data.get('contract_date', '')
    course = data.get('course', '')
    df = data.get('date_from', '')
    dt = data.get('date_to', '')
    branch = data.get('branch', '')
    total = data.get('total_amount', '')
    month_amt = data.get('month_amount', '')
    disc = data.get('discount_amount', '')
    pfio = data.get('parent_fio', '')
    piin = data.get('parent_iin', '')
    pdoc = data.get('parent_doc_num', '')
    pdoc_date = data.get('parent_doc_date', '')
    pphone = data.get('parent_phone', '')
    paddr = data.get('parent_address', '')
    cfio = data.get('child_fio', '')
    ciin = data.get('child_iin', '')

    cd = parse_date(cdate)
    dfd = parse_date(df)
    dtd = parse_date(dt)
    pdd = parse_date(pdoc_date)

    total_str, total_words, total_n = fmt_num(total)
    month_str, month_words, _ = fmt_num(month_amt)
    disc_str, disc_words, _ = fmt_num(disc)

    paras = doc.paragraphs

    # === P1: Contract number ===
    # run0='ОБ ОКАЗАНИИ ОБРАЗОВАТЕЛЬНЫХ УСЛУГ №', run1='____________'
    p1 = paras[1]
    if len(p1.runs) > 1:
        p1.runs[1].text = num

    # === P2: Date line ===
    # Mahsutov (15 runs): run9=day, run12=month, run13=' 202', run14=year_last
    # Bilim    (13 runs): run7='\t...«', run8=day(spaces), run9='»', run11=month, run12=' 202X г.'
    if cd:
        p2 = paras[2]
        r = p2.runs
        if len(r) > 14:
            # Mahsutov structure
            r[9].text = cd['day']
            r[12].text = cd['month_num']
            r[13].text = ' 202'
            r[14].text = cd['year_last']
        elif len(r) > 11:
            # Bilim structure
            r[8].text = cd['day']
            r[11].text = cd['month_num']
            r[12].text = ' ' + cd['year'] + ' г. '

    # === P4: Parent data ===
    # Mahsutov (32 runs): run16=fio, run18=iin, run19=doc, run22=day, run23=month, run27=addr
    # Bilim    (31 runs): run15=fio, run17=iin, run18=doc, run21=day, run22=month, run26=addr
    p4 = paras[4]
    r4 = p4.runs
    n = len(r4)
    if n > 27:
        # Detect by checking run content
        # Mahsutov has '(далее – «Центр»)' in run15, Bilim in run14
        if 'далее' in r4[15].text:
            # Mahsutov: fio at run16
            fio_idx, iin_idx, doc_idx = 16, 18, 19
            day_idx, month_idx, addr_idx = 22, 23, 27
        else:
            # Bilim: fio at run15
            fio_idx, iin_idx, doc_idx = 15, 17, 18
            day_idx, month_idx, addr_idx = 21, 22, 26

        r4[fio_idx].text = pfio + ','
        r4[fio_idx - 1].text = '\nИИН ' if fio_idx == 16 else r4[fio_idx-1].text
        r4[iin_idx - 1].text = '\nИИН '
        r4[iin_idx].text = piin + ', '
        r4[doc_idx].text = 'удостоверение личности № ' + pdoc
        r4[doc_idx + 1].text = ''
        r4[doc_idx + 2].text = ', выдано «'
        if pdd:
            r4[day_idx].text = pdd['day'] + '»'
            r4[month_idx].text = ' ' + pdd['month_num'] + ' 20' + pdd['year'][2:]
        else:
            r4[day_idx].text = '»'
            r4[month_idx].text = ' ____'
        r4[addr_idx].text = ': _____________________________ ('

    # === P5: Child data ===
    # run1=': fio,', run5='iin, '
    p5 = paras[5]
    r5 = p5.runs
    if len(r5) > 5:
        r5[1].text = ': ' + cfio + ','
        r5[5].text = ciin + ', '

    # === P7: Course ===
    # run2='__________________________'
    p7 = paras[7]
    if len(p7.runs) > 2:
        p7.runs[2].text = course

    # === P8: Period ===
    # Mahsutov (11 runs): run0=text+day, run1='» ', run2=month+' 202', run3=year_last...
    # Bilim    (10 runs): run0=text (no day), run1='» ', run2=month+year, run3='г.'...
    if dfd and dtd:
        p8 = paras[8]
        r8 = p8.runs
        if len(r8) > 10:
            # Mahsutov
            r8[0].text = f'1.2. Период оказания Услуг по настоящему Договору составляет с «{dfd["day"]}» '
            r8[1].text = ''
            r8[2].text = dfd['month_name'] + ' 202'
            r8[3].text = dfd['year_last']
            r8[4].text = ' '
            r8[5].text = 'г. '
            r8[6].text = 'по «'
            r8[7].text = dtd['day']
            r8[8].text = '» '
            r8[9].text = dtd['month_name'] + ' '
            r8[10].text = dtd['year'] + ' г.'
        else:
            # Bilim — run0 has full text up to «, run1 is blank after «
            r8[0].text = f'1.2. Период оказания Услуг по настоящему Договору составляет с «{dfd["day"]}» '
            r8[1].text = ''
            r8[2].text = dfd['month_name'] + ' ' + dfd['year'] + ' '
            r8[3].text = 'г. '
            r8[4].text = 'по «'
            r8[5].text = dtd['day']
            r8[6].text = '» '
            r8[7].text = dtd['month_name'] + ' '
            r8[8].text = dtd['year'] + ' г.'

    # === P16: Branch 1.6 ===
    # run0='1.6...Казахстан, г. ', run1='Шымкент', run2=', ________________________________.'
    p16 = paras[16]
    if len(p16.runs) > 2:
        p16.runs[2].text = ', ' + branch + '.'

    # === TABLE 0: Requisites ===
    tbl0 = doc.tables[0]
    cell_parent = tbl0.rows[0].cells[1]
    cell_paras = cell_parent.paragraphs

    # P1: FIO
    if len(cell_paras) > 1:
        p = cell_paras[1]
        if p.runs:
            p.runs[0].text = 'ФИО: ' + pfio
            for r in p.runs[1:]: r.text = ''
        else:
            from docx.oxml import OxmlElement
            r = p.add_run('ФИО: ' + pfio)

    # P2: IIN
    if len(cell_paras) > 2:
        p = cell_paras[2]
        if p.runs:
            p.runs[0].text = 'ИИН  ' + piin
            for r in p.runs[1:]: r.text = ''

    # P3: Doc number
    if len(cell_paras) > 3:
        p = cell_paras[3]
        if p.runs:
            p.runs[0].text = 'удостоверение личности № ' + pdoc
            for r in p.runs[1:]: r.text = ''

    # P4: Issue date
    if len(cell_paras) > 4:
        p = cell_paras[4]
        date_txt = f'выдано МВД РК от «{pdd["day"]}» {pdd["month_num"]} 20{pdd["year"][2:]}г.' if pdd else 'выдано МВД РК от '
        if p.runs:
            p.runs[0].text = date_txt
            for r in p.runs[1:]: r.text = ''

    # P5: Address
    if len(cell_paras) > 5:
        p = cell_paras[5]
        if p.runs:
            p.runs[0].text = 'Адрес: ' + paddr
            for r in p.runs[1:]: r.text = ''

    # P6: Phone
    if len(cell_paras) > 6 and pphone:
        p = cell_paras[6]
        if p.runs:
            p.runs[0].text = 'Конт.тел'
            if len(p.runs) > 1:
                p.runs[1].text = '.: ' + pphone
                for r in p.runs[2:]: r.text = ''

    # === TABLE 1: Appendix 1 ===
    tbl1 = doc.tables[1]

    # Row 0: Total amount + dates
    # P0: dates, P1: amount + words
    cell_total = tbl1.rows[0].cells[2]
    cp = cell_total.paragraphs
    if dfd and dtd and len(cp) > 0:
        r = cp[0].runs
        # run1='\\nс «', run2='» ', run3='_______ 202', run4='6', run6='г. ', run7='по «', run8='» ', run9='_______ 2026 ', run10='г. составляет:'
        if len(r) > 10:
            r[2].text = dfd['day'] + '» '
            r[3].text = dfd['month_name'] + ' 202'
            r[4].text = dfd['year_last']
            r[8].text = dtd['day'] + '» '
            r[9].text = dtd['month_name'] + ' ' + dtd['year'] + ' '

    if total and len(cp) > 1:
        # P1run0 = '1 066 500 (Один миллион...)'
        p1r = cp[1].runs
        if p1r:
            p1r[0].text = f'{total_str} ({total_words})'
            for r in p1r[1:]: r.text = ''

    # Row 1: Month amount
    # P0run2 = '124 000 (Сто двадцать четыре тысячи) тенге.'
    if month_amt:
        cell_month = tbl1.rows[1].cells[2]
        mp = cell_month.paragraphs
        if mp:
            mr = mp[0].runs
            if len(mr) > 2:
                mr[2].text = f'{month_str} ({month_words}) тенге.'
                for r in mr[3:]: r.text = ''

    # Row 2: Discount
    # P1run2='1 066 500 тенге', P2run0='853 200 (Восемьсот...)'
    if disc:
        cell_disc = tbl1.rows[2].cells[2]
        dp = cell_disc.paragraphs
        if len(dp) > 2:
            # P1: total reference
            dr1 = dp[1].runs
            if len(dr1) > 2:
                dr1[2].text = f'{total_str} тенге'
                for r in dr1[3:]: r.text = ''
            # P2: discount amount
            dr2 = dp[2].runs
            if dr2:
                dr2[0].text = f'{disc_str} ({disc_words}) тенге.'
                for r in dr2[1:]: r.text = ''

    # Row 4: Branch
    # run2=', ________________________'
    cell_branch = tbl1.rows[4].cells[2]
    br = cell_branch.paragraphs[0].runs if cell_branch.paragraphs else []
    if len(br) > 2:
        br[2].text = ', ' + branch

    # === P153: Appendix 1 date ===
    # Mahsutov: 3 runs — run0='от «____» _______ 202', run1='6', run2=' года'
    # Bilim:    1 run  — run0='от «____» _______ 2025 года' (full text)
    if cd:
        p153 = paras[153]
        r153 = p153.runs
        if len(r153) > 1:
            # Mahsutov: multiple runs
            r153[0].text = f'от «{cd["day"]}» {cd["month_num"]} 202'
            r153[1].text = cd['year_last']
            if len(r153) > 2:
                r153[2].text = ' года'
        elif len(r153) == 1:
            # Bilim: single run
            r153[0].text = f'от «{cd["day"]}» {cd["month_num"]} {cd["year"]} года'

        # === P157: App1 city+date ===
        # Mahsutov: 7 runs with date
        # Bilim: 3 runs, no date (date is missing from template)
        p157 = paras[157]
        r157 = p157.runs
        if len(r157) > 5:
            # Mahsutov
            r157[4].text = cd['day'] + '» ' + cd['month_num'] + ' 202'
            r157[5].text = cd['year_last']
            if len(r157) > 6:
                r157[6].text = ' года'
        elif len(r157) == 3:
            # Bilim — add date to the end of run2
            r157[2].text = r157[2].text.rstrip() + '   «' + cd['day'] + '» ' + cd['month_num'] + ' ' + cd['year'] + ' года'

    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()
