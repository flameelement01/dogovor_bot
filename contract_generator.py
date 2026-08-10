"""
Contract generator based on real .docx templates.
Replaces variable data in template runs by searching for placeholder content.
Works for both Mahsutov and Bilim templates.
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


def generate_contract(data, template_path):
    doc = Document(template_path)

    # Detect template by filename
    mahsutov = 'mahsutov' in template_path

    num = data.get('contract_num') or ''
    cdate = data.get('contract_date') or ''
    course = data.get('course') or ''
    df = data.get('date_from') or ''
    dt = data.get('date_to') or ''
    branch = data.get('branch') or ''
    total = data.get('total_amount') or ''
    month_amt = data.get('month_amount') or ''
    disc = data.get('discount_amount') or ''
    pfio = data.get('parent_fio') or ''
    piin = data.get('parent_iin') or ''
    pdoc = data.get('parent_doc_num') or ''
    pdoc_date = data.get('parent_doc_date') or ''
    pphone = data.get('parent_phone') or ''
    cfio = data.get('child_fio') or ''
    ciin = data.get('child_iin') or ''

    cd = parse_date(cdate)
    dfd = parse_date(df)
    dtd = parse_date(dt)
    pdd = parse_date(pdoc_date)

    total_str, total_words, _ = fmt_num(total)
    month_str, month_words, _ = fmt_num(month_amt)
    disc_str, disc_words, _ = fmt_num(disc)

    paras = doc.paragraphs

    # === P1: Contract number ===
    p1 = paras[1]
    if len(p1.runs) > 1:
        p1.runs[1].text = num

    # === P2: Contract date ===
    # Bilim:    day=r[10], month=r[13], year_last=r[15]  (r[14]=' 202' stays)
    # Mahsutov: day=r[9],  month=r[12], full year in r[13]
    if cd:
        p2 = paras[2]
        r = p2.runs
        if mahsutov:
            if len(r) > 13:
                r[9].text  = cd['day']
                r[12].text = cd['month_num']
                r[13].text = ' ' + cd['year'] + ' г. '
        else:
            if len(r) > 15:
                r[10].text = cd['day']
                r[13].text = cd['month_num']
                r[15].text = cd['year_last']

    # === P4: Parent data ===
    # Bilim:    pre-filled names at r[15](last)/r[17](first+mid), date at r[25] as DD.MM.YYYY
    # Mahsutov: '____' placeholder at r[16], ', выдано «' at r[21]
    p4 = paras[4]
    r4 = p4.runs

    if not mahsutov:
        # Positional FIO write (template has pre-filled data, no ____ placeholders)
        parts = pfio.strip().split()
        if len(r4) > 17:
            r4[15].text = parts[0] if parts else pfio
            r4[16].text = ' '
            r4[17].text = ' '.join(parts[1:]) if len(parts) > 1 else ''
    else:
        for ri, run in enumerate(r4):
            t = run.text
            if '____' in t and ri > 5 and 'далее' not in t and 'адресу' not in t and 'МВД' not in t and 'проживающий' not in t:
                run.text = pfio + ','
                break

    for ri, run in enumerate(r4):
        if '\nИИН' in run.text:
            if ri + 1 < len(r4):
                r4[ri+1].text = piin + ', '
            break

    if not mahsutov:
        # Bilim: r[21]=label, r[22]=pre-filled number → overwrite r[22] with pdoc
        for ri, run in enumerate(r4):
            if 'удостоверение личности №' in run.text:
                run.text = 'удостоверение личности № '
                if ri+1 < len(r4):
                    r4[ri+1].text = pdoc
                break
        # Bilim: r[24]='выдано ', r[25]=pre-filled date as DD.MM.YYYY
        for ri, run in enumerate(r4):
            if run.text.strip() == 'выдано':
                if pdd and ri+1 < len(r4):
                    r4[ri+1].text = f'{pdd["day"]}.{pdd["month_num"]}.{pdd["year"]}'
                break
    else:
        for ri, run in enumerate(r4):
            if 'удостоверение личности №' in run.text:
                run.text = 'удостоверение личности № ' + pdoc
                if ri+1 < len(r4) and '_' in r4[ri+1].text:
                    r4[ri+1].text = ''
                break
        for ri, run in enumerate(r4):
            if ', выдано «' in run.text:
                run.text = ', выдано «'
                if pdd:
                    if ri+1 < len(r4): r4[ri+1].text = pdd['day'] + '»'
                    if ri+2 < len(r4): r4[ri+2].text = ' ' + pdd['month_num'] + ' 20' + pdd['year'][2:]
                else:
                    if ri+1 < len(r4): r4[ri+1].text = '»'
                    if ri+2 < len(r4): r4[ri+2].text = ' ____'
                break

    # === P5: Child data ===
    # Bilim:    run[0]='Слушатель: ', run[1]=FIO (any value — positional write)
    # Mahsutov: run[0]='Слушатель',  run[1]=': FIO placeholder', run[2]=','
    p5 = paras[5]
    r5 = p5.runs
    if not mahsutov:
        # Bilim: FIO is always run[1] regardless of whether template is blank or pre-filled
        if len(r5) > 1:
            r5[1].text = cfio
    else:
        for ri, run in enumerate(r5):
            if '____' in run.text and 'Слушатель' not in run.text:
                run.text = ': ' + cfio
                break
    for ri, run in enumerate(r5):
        if run.text == 'ИИН ':
            if ri+1 < len(r5):
                r5[ri+1].text = ciin + ', '
            break

    # === P7: Course ===
    p7 = paras[7]
    if len(p7.runs) > 2:
        p7.runs[2].text = course

    # === P8: Period ===
    # Bilim (14 runs):    day=r[1], month=r[3], year_last=r[5], to_day=r[8], to_month=r[10], to_year=r[12]
    # Mahsutov (10 runs): from_day embedded in r[0], from_month+year=r[2], to_day=r[5], to_month=r[7], to_year=r[8]
    if dfd and dtd:
        p8 = paras[8]
        r8 = p8.runs
        if mahsutov:
            if len(r8) > 8:
                r8[0].text = f'1.2. Период оказания Услуг по настоящему Договору составляет с «{dfd["day"]}'
                r8[2].text = dfd['month_num'] + ' ' + dfd['year'] + ' '
                r8[5].text = dtd['day']
                r8[7].text = dtd['month_num'] + ' '
                r8[8].text = dtd['year'] + ' г.'
        else:
            if len(r8) > 12:
                r8[1].text  = dfd['day']
                r8[3].text  = dfd['month_num']
                r8[5].text  = dfd['year_last']
                r8[8].text  = dtd['day']
                r8[10].text = dtd['month_num']
                r8[12].text = dtd['year'] + ' г.'

    # === P16: Branch ===
    # Bilim (4 runs):    run[2]=', ', run[3]=address placeholder → set run[3]
    # Mahsutov (3 runs): run[2]=', филиал: ___.' → replace entirely
    p16 = paras[16]
    br16 = p16.runs
    if len(br16) > 3:
        br16[2].text = ', '
        br16[3].text = branch
    elif len(br16) > 2:
        br16[2].text = ', ' + branch + '.'

    # === TABLE 0: Requisites ===
    tbl0 = doc.tables[0]
    cell_parent = tbl0.rows[0].cells[1]
    cp = cell_parent.paragraphs

    def set_cell_para(paras_list, idx, text):
        if idx < len(paras_list):
            p = paras_list[idx]
            if p.runs:
                p.runs[0].text = text
                for r in p.runs[1:]: r.text = ''

    set_cell_para(cp, 1, 'ФИО: ' + pfio)
    set_cell_para(cp, 2, 'ИИН  ' + piin)
    set_cell_para(cp, 3, 'удостоверение личности № ' + pdoc)
    if pdd:
        set_cell_para(cp, 4, f'выдано МВД РК от «{pdd["day"]}» {pdd["month_num"]} 20{pdd["year"][2:]}г.')
    if pphone and len(cp) > 6:
        set_cell_para(cp, 6, 'Конт.тел.: ' + pphone)

    # === TABLE 1: Appendix 1 ===
    tbl1 = doc.tables[1]

    # Row 0: period dates + total amount
    cell_total = tbl1.rows[0].cells[2]
    cp0 = cell_total.paragraphs
    if dfd and dtd and len(cp0) > 0:
        r = cp0[0].runs
        if mahsutov:
            # from_day goes into r[2] (between «» of r[1] and r[2]), from_month+year=r[3]
            # to_day goes into r[6], to_month+year=r[7]
            if len(r) > 7:
                r[2].text = f'{dfd["day"]}» '
                r[3].text = f'{dfd["month_num"]} {dfd["year"]} '
                r[6].text = f'{dtd["day"]}» '
                r[7].text = f'{dtd["month_num"]} {dtd["year"]} '
        else:
            # Entire period is one string in r[2]
            if len(r) > 2:
                r[2].text = (
                    f'«{dfd["day"]}» {dfd["month_num"]} {dfd["year"]} г. '
                    f'по «{dtd["day"]}» {dtd["month_num"]} {dtd["year"]} '
                )

    if total and len(cp0) > 1:
        p1r = cp0[1].runs
        if p1r:
            p1r[0].text = f'{total_str} ({total_words}) тенге.'
            for r in p1r[1:]: r.text = ''

    # Row 1: Month amount — run[2] holds the value in both templates
    if month_amt:
        cell_month = tbl1.rows[1].cells[2]
        mp = cell_month.paragraphs
        if mp:
            mr = mp[0].runs
            if len(mr) > 2:
                mr[2].text = f'{month_str} ({month_words}) тенге.'
                for r in mr[3:]: r.text = ''

    # Row 2: Discount
    if disc:
        cell_disc = tbl1.rows[2].cells[2]
        dp = cell_disc.paragraphs
        if len(dp) > 2:
            dr1 = dp[1].runs
            if len(dr1) > 2:
                dr1[2].text = f'{total_str} тенге'
                for r in dr1[3:]: r.text = ''
            dr2 = dp[2].runs
            if dr2:
                dr2[0].text = f'{disc_str} ({disc_words}) тенге.'
                for r in dr2[1:]: r.text = ''

    # Row 4: Branch
    # Bilim (4 runs): run[2]=', ', run[3]=address → same logic as P16
    # Mahsutov (3 runs): run[2]=', филиал: ___' → replace with ', branch'
    cell_branch = tbl1.rows[4].cells[2]
    br = cell_branch.paragraphs[0].runs if cell_branch.paragraphs else []
    if len(br) > 3:
        br[2].text = ', '
        br[3].text = branch
    elif len(br) > 2:
        br[2].text = ', ' + branch

    # Remove пункт 5 (Заморозка) for graduating classes (5/10/11/12 grade)
    if data.get('contract_type') == 'graduate' and len(tbl1.rows) > 5:
        tr = tbl1.rows[5]._tr
        tr.getparent().remove(tr)

    # === Appendix 1 date line ===
    # Bilim:    P153 (runs=3) — r[0]='от ', r[1]='«day» month year ', r[2]='года'
    # Mahsutov: P157 (runs=1) — single run with full date placeholder
    if cd:
        date_para_idx = 157 if mahsutov else 153
        city_para_idx = 161 if mahsutov else 157

        p_date = paras[date_para_idx]
        r_date = p_date.runs
        if len(r_date) > 1:
            r_date[0].text = f'от «{cd["day"]}» {cd["month_num"]} 202'
            r_date[1].text = cd['year_last']
            if len(r_date) > 2: r_date[2].text = ' года'
        elif r_date:
            r_date[0].text = f'от «{cd["day"]}» {cd["month_num"]} {cd["year"]} года'

        # === Appendix 1 city + date line ===
        # Bilim P157 (7 runs):    r[4]='«', r[5]='day» month year ', r[6]='года'
        # Mahsutov P161 (5 runs): r[3]='   «', r[4]='day» month year года'
        p_city = paras[city_para_idx]
        r_city = p_city.runs
        if mahsutov:
            if len(r_city) > 4:
                r_city[4].text = f'{cd["day"]}» {cd["month_num"]} {cd["year"]} года'
        else:
            if len(r_city) > 5:
                r_city[5].text = f'{cd["day"]}» {cd["month_num"]} {cd["year"]} '

    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()
