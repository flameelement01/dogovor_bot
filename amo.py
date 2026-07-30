import os
import requests
from datetime import datetime

DOMAIN = os.getenv('AMOCRM_DOMAIN', '')
TOKEN = os.getenv('AMOCRM_TOKEN', '')

# Deal custom field IDs
F_CONTRACT_NUM  = 425865
F_CHILD_IIN     = 435051
F_CHILD_FIRST   = 442131
F_CHILD_LAST    = 442133
F_CHILD_MIDDLE  = 874697
F_DATE_FROM     = 374505
F_DATE_TO       = 89203
F_BRANCH        = 871521
F_IP            = 910977
F_COURSE        = 89095
F_CLASS         = 96029   # Класс обучения — determines contract_type
F_MONTH_AMOUNT  = 899103  # Месяц по договору

# Contact custom field IDs
FC_PARENT_IIN     = 898217
FC_PHONE          = 83341
FC_PARENT_DOC_NUM = 914013  # Номер удостоверения
FC_PARENT_DOC_DATE = 914015  # Дата выдачи удостоверения (date → unix ts)

# Classes that trigger "graduate" contract type
GRADUATE_CLASSES = {'5', '10', '11', '12'}

# AmoCRM branch name → contract address
BRANCH_MAP = {
    'Кунаева':    'пр. Кунаева 95/1',
    'Желтоксан':  'ул. Желтоксана 35',
    'Шаяхметова': 'ул. Шаяхметова 39',
}

# AmoCRM IP enum value (uppercase) → bot ip_key
IP_MAP = {
    'МАХСУТОВ':          'mahsutov',
    'BILIM ORTALYGY':    'bilim',
    'БІЛІМ ОРТАЛЫҒЫ':    'bilim',
    'БІЛІМ БЕРУ ОРТАЛЫҒЫ': 'bilim',
}

# AmoCRM course value → contract course string
COURSE_MAP = {
    'НИШ':           'ТОП школы (НИШ, БИЛ, РФМШ)',
    'РФМШ':          'ТОП школы (НИШ, БИЛ, РФМШ)',
    'КТЛ':           'ТОП школы (НИШ, БИЛ, РФМШ)',
    '165 лицей':     'ТОП школы (НИШ, БИЛ, РФМШ)',
    'ЕНТ':           'ЕНТ',
    'Повысить уровень': 'Повышение уровня знаний',
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
    """For multiselect fields — returns list of values."""
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
        return datetime.fromtimestamp(int(ts)).strftime('%d.%m.%Y')
    except Exception:
        return None


def _map_branch(raw):
    if not raw:
        return None
    for key, addr in BRANCH_MAP.items():
        if key in raw:
            return addr
    return raw  # use as-is for unknown branches


def _map_ip(raw_list):
    """Map list of IP enum values to ip_key."""
    for raw in raw_list:
        upper = raw.upper()
        for key, ip_key in IP_MAP.items():
            if key in upper:
                return ip_key
    return None


def _map_course(raw_list):
    if not raw_list:
        return None
    mapped = []
    for v in raw_list:
        mapped.append(COURSE_MAP.get(v, v))
    # deduplicate preserving order
    seen = set()
    result = []
    for m in mapped:
        if m not in seen:
            seen.add(m)
            result.append(m)
    return ', '.join(result) if result else None


def fetch_deal(deal_id):
    """
    Fetch deal + contact from AmoCRM.
    Returns (data_dict, error_string). On success error_string is None.
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

    child_first  = _field_value(cfv, F_CHILD_FIRST) or ''
    child_last   = _field_value(cfv, F_CHILD_LAST) or ''
    child_middle = _field_value(cfv, F_CHILD_MIDDLE) or ''
    parts = [p for p in [child_last, child_first, child_middle] if p]
    child_fio = ' '.join(parts) or None

    branch_raw  = _field_value(cfv, F_BRANCH)
    ip_raw_list = _field_values_list(cfv, F_IP)
    course_list = _field_values_list(cfv, F_COURSE)

    # Contract type from class number
    class_val = str(_field_value(cfv, F_CLASS) or '')
    contract_type = 'graduate' if class_val in GRADUATE_CLASSES else 'regular'

    # "Бюджет" (deal.price) = сумма со скидкой
    price = lead.get('price')
    discount_amount = str(price) if price else None

    month_raw = _field_value(cfv, F_MONTH_AMOUNT)
    month_amount = str(month_raw).replace(' ', '').replace(',', '') if month_raw else None

    data = {
        'contract_num':   _field_value(cfv, F_CONTRACT_NUM),
        'child_iin':      _field_value(cfv, F_CHILD_IIN),
        'child_fio':      child_fio,
        'date_from':      _ts_to_date(_field_value(cfv, F_DATE_FROM)),
        'date_to':        _ts_to_date(_field_value(cfv, F_DATE_TO)),
        'branch':         _map_branch(branch_raw),
        'ip':             _map_ip(ip_raw_list),
        'course':         _map_course(course_list),
        'contract_type':  contract_type,
        'month_amount':   month_amount,
        'discount_amount': discount_amount,
    }

    # Fetch contact for parent data
    contacts = (lead.get('_embedded') or {}).get('contacts') or []
    if contacts:
        cid = contacts[0]['id']
        try:
            rc = requests.get(
                f'https://{DOMAIN}/api/v4/contacts/{cid}?with=custom_fields_values',
                headers=_headers(), timeout=10
            )
            if rc.status_code == 200:
                contact = rc.json()
                ccfv = contact.get('custom_fields_values') or []
                data['parent_fio'] = contact.get('name')
                data['parent_iin'] = _field_value(ccfv, FC_PARENT_IIN)
                data['parent_phone'] = _field_value(ccfv, FC_PHONE)
                data['parent_doc_num'] = str(_field_value(ccfv, FC_PARENT_DOC_NUM) or '') or None
                data['parent_doc_date'] = _ts_to_date(_field_value(ccfv, FC_PARENT_DOC_DATE))
        except Exception:
            pass

    return data, None
