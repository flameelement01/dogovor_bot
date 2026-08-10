import os
import requests
from datetime import datetime

DOMAIN = os.getenv('AMOCRM_DOMAIN', '')
TOKEN = os.getenv('AMOCRM_TOKEN', '')

# Deal custom field IDs (core)
F_CHILD_IIN     = 435051
F_CHILD_FIRST   = 442131
F_CHILD_LAST    = 442133
F_CHILD_MIDDLE  = 874697
F_DATE_FROM     = 374505
F_DATE_TO       = 89203
F_BRANCH        = 871521
F_IP            = 910977
F_COURSE        = 89095
F_CLASS         = 96029   # Класс обучения → contract_type
F_MONTH_AMOUNT  = 899103  # Месяц по договору

# Deal custom field IDs — группа "Договор" (новые поля)
FD_PARENT_FIO    = 914025  # ФИО родителя
FD_PARENT_IIN    = 914031  # ИИН родителя
FD_DOC_NUM       = 914021  # Номер удостоверения
FD_DOC_DATE      = 914023  # Дата выдачи удостоверения
FD_DOC_ISSUER    = 914033  # Кем выдано
FD_CHILD_FIO     = 914029  # ФИО ребенка (единое поле)
FD_PRICE_NO_DISC = 914027  # Цена абонемента (без скидки)

# Contact custom field IDs (fallback)
FC_PARENT_IIN     = 898217
FC_PHONE          = 83341
FC_PARENT_DOC_NUM = 914013
FC_PARENT_DOC_DATE = 914015
FC_PARENT_FIO     = 914017

# Classes that trigger "graduate" contract type
GRADUATE_CLASSES = {'5', '10', '11', '12'}

BRANCH_MAP = {
    'Дулати':     'пр. Кунаева 95/1',
    'Желтоксан':  'ул. Желтоксана 35',
    'Шаяхметова': 'ул. Шаяхметова 39',
}

IP_MAP = {
    'МАХСУТОВ':            'mahsutov',
    'BILIM ORTALYGY':      'bilim',
    'БІЛІМ ОРТАЛЫҒЫ':      'bilim',
    'БІЛІМ БЕРУ ОРТАЛЫҒЫ': 'bilim',
}

COURSE_MAP = {
    'НИШ':             'ТОП школы (НИШ, БИЛ, РФМШ)',
    'РФМШ':            'ТОП школы (НИШ, БИЛ, РФМШ)',
    'КТЛ':             'ТОП школы (НИШ, БИЛ, РФМШ)',
    '165 лицей':       'ТОП школы (НИШ, БИЛ, РФМШ)',
    'ЕНТ':             'ЕНТ',
    'Повысить уровень':'Повышение уровня знаний',
}


def _headers():
    return {'Authorization': f'Bearer {TOKEN}', 'Content-Type': 'application/json'}


def _field_value(cfv, field_id):
    if not cfv or not field_id:
        return None
    for f in cfv:
        if f.get('field_id') == field_id:
            vals = f.get('values', [])
            if vals:
                return vals[0].get('value')
    return None


def _field_values_list(cfv, field_id):
    if not cfv or not field_id:
        return []
    for f in cfv:
        if f.get('field_id') == field_id:
            return [v.get('value') for v in f.get('values', [])]
    return []


def _ts_to_date(ts):
    if not ts:
        return None
    try:
        # AMO stores date-only fields as midnight Kazakhstan time (UTC+5).
        # Add 5h so UTC servers get the correct calendar date.
        return datetime.utcfromtimestamp(int(ts) + 5 * 3600).strftime('%d.%m.%Y')
    except Exception:
        return None


def _nonempty(val):
    """Return val if truthy string, else None."""
    s = str(val).strip() if val is not None else ''
    return s or None


def _map_branch(raw):
    if not raw:
        return None
    for key, addr in BRANCH_MAP.items():
        if key in raw:
            return addr
    return raw


def _map_ip(raw_list):
    for raw in raw_list:
        upper = raw.upper()
        for key, ip_key in IP_MAP.items():
            if key in upper:
                return ip_key
    return None


def _map_course(raw_list):
    if not raw_list:
        return None
    seen, result = set(), []
    for v in raw_list:
        mapped = COURSE_MAP.get(v, v)
        if mapped not in seen:
            seen.add(mapped)
            result.append(mapped)
    return ', '.join(result) if result else None


def fetch_deal(deal_id):
    """
    Fetch deal + contact from AmoCRM.
    Returns (data_dict, error_string). On success error_string is None.
    Priority: new deal fields (группа Договор) → old contact fields.
    """
    if not DOMAIN or not TOKEN:
        return None, 'AmoCRM не настроен (нет DOMAIN или TOKEN)'

    url = f'https://{DOMAIN}/api/v4/leads/{deal_id}?with=contacts,custom_fields_values'
    try:
        r = requests.get(url, headers=_headers(), timeout=10)
    except Exception as e:
        return None, f'Ошибка сети: {e}'

    if r.status_code == 404:
        return None, f'Сделка #{deal_id} не найдена'
    if r.status_code != 200:
        return None, f'AmoCRM вернул ошибку {r.status_code}'

    lead = r.json()
    cfv = lead.get('custom_fields_values') or []

    # ФИО ребёнка: новое единое поле → собираем из старых полей
    child_fio_new = _nonempty(_field_value(cfv, FD_CHILD_FIO))
    if not child_fio_new:
        parts = [p for p in [
            _field_value(cfv, F_CHILD_LAST) or '',
            _field_value(cfv, F_CHILD_FIRST) or '',
            _field_value(cfv, F_CHILD_MIDDLE) or '',
        ] if p]
        child_fio_new = ' '.join(parts) or None

    branch_raw  = _field_value(cfv, F_BRANCH)
    ip_raw_list = _field_values_list(cfv, F_IP)
    course_list = _field_values_list(cfv, F_COURSE)

    class_val = str(_field_value(cfv, F_CLASS) or '')
    contract_type = 'graduate' if class_val in GRADUATE_CLASSES else 'regular'

    price = lead.get('price')
    discount_amount = str(price) if price else None

    month_raw = _field_value(cfv, F_MONTH_AMOUNT)
    month_amount = str(month_raw).replace(' ', '').replace(',', '') if month_raw else None

    # Новые поля группы "Договор" из сделки
    parent_fio_deal   = _nonempty(_field_value(cfv, FD_PARENT_FIO))
    parent_iin_deal   = _nonempty(_field_value(cfv, FD_PARENT_IIN))
    doc_num_deal      = _nonempty(_field_value(cfv, FD_DOC_NUM))
    doc_date_deal     = _ts_to_date(_field_value(cfv, FD_DOC_DATE))
    doc_issuer_deal   = _nonempty(_field_value(cfv, FD_DOC_ISSUER))
    price_no_disc     = _nonempty(_field_value(cfv, FD_PRICE_NO_DISC))

    data = {
        'contract_num':    str(deal_id),
        'child_iin':       _field_value(cfv, F_CHILD_IIN),
        'child_fio':       child_fio_new,
        'date_from':       _ts_to_date(_field_value(cfv, F_DATE_FROM)),
        'date_to':         _ts_to_date(_field_value(cfv, F_DATE_TO)),
        'branch':          _map_branch(branch_raw),
        'ip':              _map_ip(ip_raw_list),
        'course':          _map_course(course_list),
        'contract_type':   contract_type,
        'month_amount':    month_amount,
        'total_amount':    _nonempty(_field_value(cfv, FD_PRICE_NO_DISC)),
        'discount_amount': discount_amount,
        # Договор group — deal level
        'parent_fio':      parent_fio_deal,
        'parent_iin':      parent_iin_deal,
        'parent_doc_num':  doc_num_deal,
        'parent_doc_date': doc_date_deal,
        'parent_doc_issuer': doc_issuer_deal,
    }

    # Fetch contact for phone + fallback fields
    data['_contact_id'] = None
    contacts = (lead.get('_embedded') or {}).get('contacts') or []
    if contacts:
        cid = contacts[0]['id']
        data['_contact_id'] = cid
        try:
            rc = requests.get(
                f'https://{DOMAIN}/api/v4/contacts/{cid}?with=custom_fields_values',
                headers=_headers(), timeout=10
            )
            if rc.status_code == 200:
                contact = rc.json()
                ccfv = contact.get('custom_fields_values') or []
                data['parent_phone'] = _field_value(ccfv, FC_PHONE)
                data['_contact_city'] = _field_value(ccfv, 893245)
                # Fallback: use contact fields if deal fields are empty
                if not data['parent_fio']:
                    data['parent_fio'] = _nonempty(_field_value(ccfv, FC_PARENT_FIO)) or contact.get('name')
                if not data['parent_iin']:
                    data['parent_iin'] = _nonempty(_field_value(ccfv, FC_PARENT_IIN))
                if not data['parent_doc_num']:
                    data['parent_doc_num'] = _nonempty(_field_value(ccfv, FC_PARENT_DOC_NUM))
                if not data['parent_doc_date']:
                    data['parent_doc_date'] = _ts_to_date(_field_value(ccfv, FC_PARENT_DOC_DATE))
        except Exception:
            pass

    return data, None


def update_deal_contract(deal_id, doc_num=None, doc_date_str=None):
    """Write parent passport fields to deal's Договор group."""
    if not deal_id:
        return
    fields = []
    if doc_num:
        fields.append({'field_id': FD_DOC_NUM, 'values': [{'value': doc_num}]})
    if doc_date_str:
        try:
            ts = int(datetime.strptime(doc_date_str, '%d.%m.%Y').timestamp())
            fields.append({'field_id': FD_DOC_DATE, 'values': [{'value': ts}]})
        except Exception:
            pass
    if not fields:
        return
    try:
        requests.patch(
            f'https://{DOMAIN}/api/v4/leads',
            json=[{'id': deal_id, 'custom_fields_values': fields}],
            headers=_headers(), timeout=10
        )
    except Exception:
        pass


def get_child_fio(deal_id):
    """Fetch current value of FD_CHILD_FIO (914029) from AMO."""
    if not DOMAIN or not TOKEN:
        return None
    try:
        r = requests.get(
            f'https://{DOMAIN}/api/v4/leads/{deal_id}?with=custom_fields_values',
            headers=_headers(), timeout=8
        )
        if r.status_code != 200:
            return None
        cfv = r.json().get('custom_fields_values') or []
        return _nonempty(_field_value(cfv, FD_CHILD_FIO))
    except Exception:
        return None


def sync_child_fio(deal_id, fio_str):
    """Parse ФИО ребёнка string and write to individual child name fields."""
    parts = fio_str.strip().split()
    last   = parts[0] if len(parts) > 0 else ''
    first  = parts[1] if len(parts) > 1 else ''
    middle = parts[2] if len(parts) > 2 else ''
    fields = []
    if last:   fields.append({'field_id': F_CHILD_LAST,   'values': [{'value': last}]})
    if first:  fields.append({'field_id': F_CHILD_FIRST,  'values': [{'value': first}]})
    if middle: fields.append({'field_id': F_CHILD_MIDDLE, 'values': [{'value': middle}]})
    if not fields:
        return
    try:
        requests.patch(
            f'https://{DOMAIN}/api/v4/leads/{deal_id}',
            json={'custom_fields_values': fields},
            headers=_headers(), timeout=10
        )
    except Exception:
        pass


def update_deal_month(deal_id, month_amount):
    """Write month amount back to AMO deal field."""
    if not deal_id or not month_amount:
        return
    try:
        requests.patch(
            f'https://{DOMAIN}/api/v4/leads',
            json=[{'id': deal_id, 'custom_fields_values': [
                {'field_id': F_MONTH_AMOUNT, 'values': [{'value': str(month_amount)}]}
            ]}],
            headers=_headers(), timeout=10
        )
    except Exception:
        pass


def add_note(deal_id, text):
    """Add a text note to a deal."""
    if not deal_id:
        return
    try:
        requests.post(
            f'https://{DOMAIN}/api/v4/leads/{deal_id}/notes',
            json=[{'entity_id': deal_id, 'note_type': 'common', 'params': {'text': text}}],
            headers=_headers(), timeout=10
        )
    except Exception:
        pass
