"""
Contract generator based on real .docx templates.
Replaces specific runs in the template with actual data.
"""
import re
import copy
from io import BytesIO
from docx import Document
from docx.oxml.ns import qn


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


def fmt_amount_words(val):
    """Format: 1 066 500 (Один миллион шестьдесят шесть тысяч пятьсот)"""
    try:
        n = int(str(val).replace(' ','').replace(',',''))
        num_str = f"{n:,}".replace(",", "\u00a0")
        return num_str, number_to_words(n)
    except:
        return str(val), ''


def parse_date(s):
    months_num = {'01':'01','02':'02','03':'03','04':'04','05':'05','06':'06',
                  '07':'07','08':'08','09':'09','10':'10','11':'11','12':'12'}
    months_name = ['января','февраля','марта','апреля','мая','июня',
                   'июля','августа','сентября','октября','ноября','декабря']
    m = re.match(r'(\d{1,2})[./](\d{1,2})[./](\d{4})', str(s))
    if m:
        d, mo, y = m.groups()
        return {
            'day': d.zfill(2),
            'month_num': mo.zfill(2),
            'month_name': months_name[int(mo)-1],
            'year': y,
            'year2': y[2:],
        }
    return None


def set_run_text(run, text):
    """Set run text preserving formatting"""
    run.text = text


def replace_runs_in_paragraph(para, replacements):
    """
    Replace text in paragraph runs.
    replacements: list of (old_text, new_text) tuples
    Works by rebuilding paragraph XML text nodes.
    """
    full_text = ''.join(r.text for r in para.runs)
    for old, new in replacements:
        full_text = full_text.replace(old, new)

    # Rebuild: put all text in first run, clear rest
    if para.runs:
        para.runs[0].text = full_text
        for run in para.runs[1:]:
            run.text = ''


def replace_in_paragraph_smart(para, replacements):
    """
    Smart replacement that preserves run formatting.
    For each replacement, find which run(s) contain the text and replace.
    """
    for old, new in replacements:
        # Try to find old text across runs
        full = ''.join(r.text for r in para.runs)
        if old not in full:
            continue

        # Simple case: text in single run
        for run in para.runs:
            if old in run.text:
                run.text = run.text.replace(old, new)
                break
        else:
            # Complex case: text spans multiple runs - rebuild first run
            new_full = full.replace(old, new)
            if para.runs:
                para.runs[0].text = new_full
                for run in para.runs[1:]:
                    run.text = ''


def generate_contract(data, template_path):
    """Generate contract from template by replacing variable data."""
    doc = Document(template_path)

    ip_key = data['ip']
    contract_num = data.get('contract_num', '___')
    cdate = data.get('contract_date', '')
    course = data.get('course', '___')
    df = data.get('date_from', '')
    dt = data.get('date_to', '')
    branch = data.get('branch', '___')
    total = data.get('total_amount', '')
    month_amt = data.get('month_amount', '')
    disc = data.get('discount_amount', '')
    pfio = data.get('parent_fio', '___')
    piin = data.get('parent_iin', '___')
    pdoc = data.get('parent_doc_num', '___')
    pdoc_date = data.get('parent_doc_date', '')
    pphone = data.get('parent_phone', '')
    paddr = data.get('parent_address', 'г. Шымкент')
    cfio = data.get('child_fio', '___')
    ciin = data.get('child_iin', '___')
    schedule = data.get('schedule', [])

    # Parse dates
    cd = parse_date(cdate)
    dfd = parse_date(df)
    dtd = parse_date(dt)
    pdd = parse_date(pdoc_date)

    # Format amounts
    total_num, total_words = fmt_amount_words(total)
    month_num, month_words = fmt_amount_words(month_amt)
    disc_num, disc_words = fmt_amount_words(disc)

    # Split parent FIO
    pfio_parts = pfio.split()
    pfio_last = pfio_parts[0] if len(pfio_parts) > 0 else ''
    pfio_first = pfio_parts[1] if len(pfio_parts) > 1 else ''
    pfio_middle = pfio_parts[2] if len(pfio_parts) > 2 else ''

    # Split child FIO
    cfio_parts = cfio.split()
    cfio_last = cfio_parts[0] if len(cfio_parts) > 0 else ''
    cfio_first = cfio_parts[1] if len(cfio_parts) > 1 else ''
    cfio_middle = cfio_parts[2] if len(cfio_parts) > 2 else ''

    # === REPLACE IN PARAGRAPHS ===

    # P1: Contract number
    p1 = doc.paragraphs[1]
    for run in p1.runs:
        if run.text.strip() and run.text.strip() not in ['ОБ ОКАЗАНИИ ОБРАЗОВАТЕЛЬНЫХ УСЛУГ №', ' ']:
            # This is the number run
            run.text = contract_num

    # P2: Date line
    if cd:
        p2 = doc.paragraphs[2]
        full = ''.join(r.text for r in p2.runs)
        # Find day/month/year runs and replace
        runs = p2.runs
        found_date_section = False
        for i, run in enumerate(runs):
            t = run.text
            # Replace day (2 digits after «)
            if t in ['23', '19', '15', '16', '17', '18', '20', '21', '22', '24', '25', '26', '27', '28', '29', '30', '31', '01', '02', '03', '04', '05', '06', '07', '08', '09', '10', '11', '12', '13', '14'] and not found_date_section:
                run.text = cd['day']
                found_date_section = True
            elif found_date_section and t in ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9'] and len(t) == 1:
                # month digits
                if run.text == '0' or run.text in ['1','2']:
                    run.text = cd['month_num'][0]
                    # next run is second digit
                    if i+1 < len(runs):
                        runs[i+1].text = cd['month_num'][1]
                    break

        # Simpler approach: replace year
        full2 = ''.join(r.text for r in p2.runs)
        # Replace in a targeted way using full text rebuild
        if cd:
            new_full = re.sub(
                r'«\d{2}»\s+\d{2}\s+202\d',
                f"«{cd['day']}»  {cd['month_num']} 202{cd['year'][3]}",
                full2
            )
            if new_full != full2 and p2.runs:
                p2.runs[0].text = new_full
                for run in p2.runs[1:]:
                    run.text = ''

    # P4: IP intro + parent data
    p4 = doc.paragraphs[4]
    full4 = ''.join(r.text for r in p4.runs)

    # Replace parent FIO parts
    replacements4 = []
    # Find existing parent name in template
    name_match = re.search(r'гражданин\(ка\) Республики Казахстан (.+?),\nИИН', full4, re.DOTALL)
    if name_match:
        old_name = name_match.group(1).strip()
        replacements4.append((old_name, pfio))

    # Replace IIN
    iin_match = re.search(r'ИИН (\d{12})', full4)
    if iin_match:
        replacements4.append((iin_match.group(1), piin))

    # Replace doc number
    doc_match = re.search(r'удостоверение личности №(\d+)', full4)
    if doc_match:
        replacements4.append((doc_match.group(1), pdoc))

    # Replace issue date
    if pdd:
        date_match = re.search(r'выдано «(\d+)»\s*(\w+)\s*(\d+)\s*(\d*)', full4)
        if not date_match:
            date_match = re.search(r'выдано «(\d+)»(\d*)\s*(\d+)\s*(\d*)', full4)

    # Replace address
    addr_match = re.search(r'проживающий\(ая\) по адресу:(.+?)\(далее', full4, re.DOTALL)
    if addr_match:
        old_addr = addr_match.group(1).strip()
        replacements4.append((old_addr, paddr))

    if replacements4:
        new_full4 = full4
        for old, new in replacements4:
            new_full4 = new_full4.replace(old, new)

        # Also fix issue date
        if pdd:
            new_full4 = re.sub(
                r'выдано «\d+»\s*\d*\s*\d+\s*\d*\s*г\.',
                f"выдано «{pdd['day']}»{pdd['month_num']} 20{pdd['year'][2:]}г.",
                new_full4
            )

        if p4.runs:
            p4.runs[0].text = new_full4
            for run in p4.runs[1:]:
                run.text = ''

    # P5: Child data
    p5 = doc.paragraphs[5]
    full5 = ''.join(r.text for r in p5.runs)
    new_full5 = full5

    # Replace child FIO
    child_match = re.search(r'Слушатель: (.+?),', full5)
    if child_match:
        new_full5 = new_full5.replace(child_match.group(1), cfio)

    # Replace child IIN
    ciin_match = re.search(r'ИИН\s*(\d{12})', full5)
    if ciin_match:
        new_full5 = new_full5.replace(ciin_match.group(1), ciin)

    if new_full5 != full5 and p5.runs:
        p5.runs[0].text = new_full5
        for run in p5.runs[1:]:
            run.text = ''

    # P7: Course name — run index 2 is always the course (between « and »)
    p7 = doc.paragraphs[7]
    if len(p7.runs) > 2:
        p7.runs[2].text = course

    # P8: Period dates
    if dfd and dtd:
        p8 = doc.paragraphs[8]
        full8 = ''.join(r.text for r in p8.runs)
        new_full8 = re.sub(
            r'с «(\d+)» (\w+) (202\d) г\.',
            f"с «{dfd['day']}» {dfd['month_name']} {dfd['year']} г.",
            full8
        )
        new_full8 = re.sub(
            r'по «(\d+)» (\w+)\s*(202\d) г\.',
            f"по «{dtd['day']}» {dtd['month_name']} {dtd['year']} г.",
            new_full8
        )
        if new_full8 != full8 and p8.runs:
            p8.runs[0].text = new_full8
            for run in p8.runs[1:]:
                run.text = ''

    # P16: Branch address (1.6)
    for p in doc.paragraphs:
        if '1.6.' in p.text and 'Услуги оказываются' in p.text:
            full = ''.join(r.text for r in p.runs)
            # Replace branch
            new_full = re.sub(r'г\. Шымкент, .+?\.', f'г. Шымкент, {branch}.', full)
            if new_full != full and p.runs:
                p.runs[0].text = new_full
                for run in p.runs[1:]:
                    run.text = ''
            break

    # === REPLACE IN TABLES ===

    # TABLE 0: Requisites
    tbl0 = doc.tables[0]

    # Cell [0][1]: Parent requisites
    cell_parent = tbl0.rows[0].cells[1]
    for para_i, para_p in enumerate(cell_parent.paragraphs):
        full_p = ''.join(r.text for r in para_p.runs)
        new_p = full_p

        if 'ФИО:' in full_p:
            # Replace FIO
            fio_match = re.search(r'ФИО:\s*(.+)', full_p)
            if fio_match:
                new_p = new_p.replace(fio_match.group(1).strip(), pfio)
        elif 'ИИН' in full_p and re.search(r'\d{12}', full_p):
            old_iin = re.search(r'\d{12}', full_p)
            if old_iin:
                new_p = new_p.replace(old_iin.group(), piin)
        elif 'удостоверение личности №' in full_p:
            old_doc = re.search(r'(\d{6,9})', full_p)
            if old_doc:
                new_p = new_p.replace(old_doc.group(), pdoc)
        elif 'выдано МВД РК' in full_p:
            if pdd:
                new_p = re.sub(
                    r'«\d+»\s*\d+\s*\d+\s*\d*\s*г?\.?',
                    f"«{pdd['day']}» {pdd['month_num']} 20{pdd['year'][2:]}г.",
                    new_p
                )
        elif 'Адрес:' in full_p:
            addr_m = re.search(r'Адрес:\s*(.+)', full_p)
            if addr_m:
                new_p = new_p.replace(addr_m.group(1).strip(), paddr)
        elif 'Конт.тел' in full_p:
            tel_m = re.search(r'\.:\s*(.+)', full_p)
            if tel_m:
                new_p = new_p.replace(tel_m.group(1).strip(), pphone if pphone else tel_m.group(1).strip())

        if new_p != full_p and para_p.runs:
            para_p.runs[0].text = new_p
            for run in para_p.runs[1:]:
                run.text = ''

    # TABLE 1: Appendix
    tbl1 = doc.tables[1]

    # Row 0: Total amount
    # Structure: P0 has date runs, P1 has amount number, P2 has 'тенге.'
    if total:
        cell_total = tbl1.rows[0].cells[2]
        paras = cell_total.paragraphs

        # P0: Replace dates (runs 14,17,18,20 = day1,month1_d1,month1_d2,year1 and 25,27,28,29 = day2,month2,year2)
        if dfd and dtd and len(paras) > 0:
            p0 = paras[0]
            runs = p0.runs
            if len(runs) > 29:
                runs[14].text = dfd['day']
                runs[17].text = dfd['month_num'][0]
                runs[18].text = dfd['month_num'][1]
                runs[19].text = ' 202'
                runs[20].text = dfd['year'][3]
                runs[25].text = dtd['day']
                runs[27].text = dtd['month_num'] + ' '
                runs[28].text = '202'
                runs[29].text = dtd['year'][3]

        # P1: Replace amount number and words
        # runs: 0='1 191', 1=nbsp, 2='000 ', 3=' (', 4='words', 5=')'
        if len(paras) > 1:
            p1 = paras[1]
            runs1 = p1.runs
            # Split total_num: e.g. '1\xa0066\xa0500' -> first part before last nbsp group
            # Simpler: put whole number in run0, clear rest, keep structure
            if runs1:
                # Rebuild: number (words)
                parts = total_num.split('\xa0')
                if len(parts) >= 3:
                    runs1[0].text = '\xa0'.join(parts[:-1])
                    if len(runs1) > 1: runs1[1].text = '\xa0'
                    if len(runs1) > 2: runs1[2].text = parts[-1] + ' '
                    if len(runs1) > 3: runs1[3].text = ' ('
                    if len(runs1) > 4: runs1[4].text = total_words
                    if len(runs1) > 5: runs1[5].text = ')'
                    for run in runs1[6:]: run.text = ''
                else:
                    runs1[0].text = f"{total_num} ({total_words})"
                    for run in runs1[1:]: run.text = ''

    # Row 1: Month amount
    if month_amt:
        cell_month = tbl1.rows[1].cells[2]
        for p in cell_month.paragraphs:
            full_p = ''.join(r.text for r in p.runs)
            if re.search(r'\d[\d\s\xa0]*(тысяч|000)', full_p) or 'тенге' in full_p:
                new_p = f"Стоимость 1 (одного) календарного месяца обучения:\n{month_num} ({month_words}) тенге."
                if p.runs:
                    p.runs[0].text = new_p
                    for run in p.runs[1:]:
                        run.text = ''
                break

    # Row 2: Discount
    # P1 runs: 0=text, 3='1 191', 5='000', 6=' тенге', 7=', Родитель...'
    # P2 runs: 0='715', 1=nbspX000, 2='(', 3=words, 4='тысяч', 5=') ', 6=' тенге', 7='.'
    if disc:
        cell_disc = tbl1.rows[2].cells[2]
        paras = cell_disc.paragraphs
        # P1: total amount reference
        if len(paras) > 1:
            p1_runs = paras[1].runs
            if len(p1_runs) > 5:
                # Split total_num by nbsp
                t_parts = total_num.replace('\xa0', ' ').split()
                if len(t_parts) >= 2:
                    p1_runs[3].text = ' '.join(t_parts[:-1])
                    if len(p1_runs) > 5: p1_runs[5].text = t_parts[-1]
                else:
                    p1_runs[3].text = total_num
                    if len(p1_runs) > 5: p1_runs[5].text = ''
        # P2: discount amount
        if len(paras) > 2:
            p2_runs = paras[2].runs
            d_parts = disc_num.replace('\xa0', ' ').split()
            if len(p2_runs) > 4 and len(d_parts) >= 2:
                p2_runs[0].text = d_parts[0]
                p2_runs[1].text = '\xa0' + ' '.join(d_parts[1:]) + ' '
                p2_runs[2].text = '('
                p2_runs[3].text = disc_words + ' '
                if len(p2_runs) > 4: p2_runs[4].text = ''
                if len(p2_runs) > 5: p2_runs[5].text = ') '
                if len(p2_runs) > 6: p2_runs[6].text = ' тенге'
                if len(p2_runs) > 7: p2_runs[7].text = '.'
            elif p2_runs:
                p2_runs[0].text = f"{disc_num} ({disc_words}) тенге."
                for run in p2_runs[1:]: run.text = ''

    # Row 4: Branch
    cell_branch = tbl1.rows[4].cells[2]
    for p in cell_branch.paragraphs:
        full_p = ''.join(r.text for r in p.runs)
        if 'филиал' in full_p:
            new_p = f"г. Шымкент, филиал: {branch}"
            if p.runs:
                p.runs[0].text = new_p
                for run in p.runs[1:]:
                    run.text = ''

    # === APPENDIX 1 DATE ===
    if cd:
        for p in doc.paragraphs:
            full_p = ''.join(r.text for r in p.runs)
            if 'от «' in full_p and '2026 года' in full_p and 'Приложение' not in full_p:
                new_p = re.sub(
                    r'от «\d+» \d+ 20\d+ года',
                    f"от «{cd['day']}» {cd['month_num']} {cd['year']} года",
                    full_p
                )
                if new_p != full_p and p.runs:
                    p.runs[0].text = new_p
                    for run in p.runs[1:]:
                        run.text = ''

        # City+date line in appendix
        for p in doc.paragraphs:
            full_p = ''.join(r.text for r in p.runs)
            if 'город Шымкент' in full_p and '«' in full_p and 'Приложение' not in full_p and p != doc.paragraphs[2]:
                new_p = re.sub(
                    r'«\d+» \d+ 20\d+ год[аы]?',
                    f"«{cd['day']}» {cd['month_num']} {cd['year']} года",
                    full_p
                )
                if new_p != full_p and p.runs:
                    p.runs[0].text = new_p
                    for run in p.runs[1:]:
                        run.text = ''

    # === APPENDIX 2 (Schedule) ===
    # Find appendix 2 table and update dates
    if schedule and len(doc.tables) > 2:
        sched_tbl = doc.tables[2]
        # Update date in header
        for p in doc.paragraphs:
            full_p = ''.join(r.text for r in p.runs)
            if 'График внесения' in full_p:
                pass  # header found
            if 'г.Шымкент' in full_p and cd:
                new_p = re.sub(
                    r'«\d+» \d+ 20\d+ год[аы]?',
                    f"«{cd['day']}» {cd['month_num']} {cd['year']} года",
                    full_p
                )
                if new_p != full_p and p.runs:
                    p.runs[0].text = new_p
                    for run in p.runs[1:]:
                        run.text = ''

        # Update schedule rows
        data_rows = [r for r in sched_tbl.rows if r.cells[0].text.strip() and r.cells[0].text.strip() != 'Дата']
        for i, sched_row in enumerate(data_rows):
            if i < len(schedule):
                entry = schedule[i]
                # Date cell
                cells = sched_row.cells
                if cells[0].paragraphs and cells[0].paragraphs[0].runs:
                    cells[0].paragraphs[0].runs[0].text = entry.get('date','')
                    for run in cells[0].paragraphs[0].runs[1:]:
                        run.text = ''
                # Amount1
                if entry.get('amount1') and cells[1].paragraphs and cells[1].paragraphs[0].runs:
                    try:
                        amt = f"{int(entry['amount1']):,}".replace(',','\u00a0')
                    except:
                        amt = entry['amount1']
                    cells[1].paragraphs[0].runs[0].text = amt
                    for run in cells[1].paragraphs[0].runs[1:]:
                        run.text = ''
                # Amount2
                if entry.get('amount2') and cells[2].paragraphs and cells[2].paragraphs[0].runs:
                    try:
                        amt = f"{int(entry['amount2']):,}".replace(',','\u00a0')
                    except:
                        amt = entry['amount2']
                    cells[2].paragraphs[0].runs[0].text = amt
                    for run in cells[2].paragraphs[0].runs[1:]:
                        run.text = ''
                # Total
                if entry.get('total') and cells[3].paragraphs and cells[3].paragraphs[0].runs:
                    try:
                        amt = f"{int(entry['total']):,}".replace(',','\u00a0')
                    except:
                        amt = entry['total']
                    cells[3].paragraphs[0].runs[0].text = amt
                    for run in cells[3].paragraphs[0].runs[1:]:
                        run.text = ''

    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()
