import re
import fitz  # PyMuPDF
import requests
import base64
import logging

logger = logging.getLogger(__name__)

GOOGLE_VISION_URL = "https://vision.googleapis.com/v1/images:annotate"


def pdf_page_to_base64(pdf_bytes, page_num=0):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[page_num]
    mat = fitz.Matrix(2.0, 2.0)
    pix = page.get_pixmap(matrix=mat)
    img_bytes = pix.tobytes("png")
    return base64.b64encode(img_bytes).decode("utf-8")


def ocr_with_google_vision(image_b64, api_key):
    payload = {
        "requests": [{
            "image": {"content": image_b64},
            "features": [{"type": "TEXT_DETECTION", "maxResults": 1}],
            "imageContext": {"languageHints": ["ru", "kk", "en"]}
        }]
    }
    resp = requests.post(
        f"{GOOGLE_VISION_URL}?key={api_key}",
        json=payload,
        timeout=30
    )
    resp.raise_for_status()
    data = resp.json()
    try:
        return data["responses"][0]["fullTextAnnotation"]["text"]
    except (KeyError, IndexError):
        return ""


def pdf_to_text(pdf_bytes, api_key):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    full_text = ""
    for i, page in enumerate(doc):
        text = page.get_text().strip()
        if len(text) > 50:
            full_text += text + "\n"
        else:
            try:
                img_b64 = pdf_page_to_base64(pdf_bytes, i)
                ocr_text = ocr_with_google_vision(img_b64, api_key)
                full_text += ocr_text + "\n"
            except Exception as e:
                logger.error(f"Vision API error on page {i}: {e}")
    return full_text.strip()


def parse_parent_fields(text):
    """Parse parent fields from KZ ID card text"""
    result = {}
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    # IIN — 12 digits
    for line in lines:
        iins = re.findall(r'\b(\d{12})\b', line)
        if iins:
            result['parent_iin'] = iins[0]
            break

    # Document number — 9 digits (like 050831499)
    for line in lines:
        if re.match(r'^\d{9}$', line.strip()):
            result['parent_doc_num'] = line.strip()
            break

    # Issue date — line with "DD.MM.YYYY - DD.MM.YYYY" (validity period)
    for line in lines:
        m = re.search(r'(\d{2}[./]\d{2}[./]\d{4})\s*[-–]\s*\d{2}[./]\d{2}[./]\d{4}', line)
        if m:
            result['parent_doc_date'] = m.group(1).replace('/', '.')
            break

    # FIO — KZ ID has SURNAME, NAME, PATRONYMIC on separate lines in ALL CAPS Cyrillic
    cyrillic_cap_lines = []
    for i, line in enumerate(lines):
        if (re.match(r'^[А-ЯЁҚҒҮҰҺІӘҢӨ\-]+$', line)
                and len(line) >= 3
                and not re.match(r'^\d+$', line)):
            cyrillic_cap_lines.append((i, line))

    # Find 2-3 consecutive uppercase Cyrillic lines
    consecutive = []
    prev_idx = -2
    for idx, line in cyrillic_cap_lines:
        if idx == prev_idx + 1:
            consecutive.append(line)
        else:
            if len(consecutive) >= 2:
                break
            consecutive = [line]
        prev_idx = idx

    if len(consecutive) >= 2:
        fio_parts = [p.capitalize() for p in consecutive[:3]]
        result['parent_fio'] = ' '.join(fio_parts)

    # Address
    text_clean = re.sub(r'\s+', ' ', text)
    addr_match = re.search(
        r'(?:мекенжай|адрес|тұрғылықты)[^\n:]*[:\s]+([^\n]{10,100})',
        text_clean, re.IGNORECASE
    )
    if addr_match:
        result['parent_address'] = addr_match.group(1).strip()

    return result


def parse_child_fields(text):
    """Parse child fields from birth certificate or ID"""
    result = {}
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    # IIN — 12 digits
    for line in lines:
        iins = re.findall(r'\b(\d{12})\b', line)
        if iins:
            result['child_iin'] = iins[0]
            break

    # FIO from birth certificate:
    # Format 1: SURNAME on one line, NAME PATRONYMIC on next line
    # Format 2: Three separate ALL CAPS lines (like ID card)
    child_fio = None

    for i, line in enumerate(lines):
        # Single ALL CAPS Cyrillic word = surname
        if re.match(r'^[А-ЯЁҚҒҮҰҺІӘҢӨ]+$', line) and len(line) > 2:
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                # Next line has 2 Cyrillic words = name + patronymic
                if re.match(r'^[А-ЯЁҚҒҮҰҺІӘҢӨ]+\s+[А-ЯЁҚҒҮҰҺІӘҢӨ]+$', next_line):
                    surname = line.capitalize()
                    rest = ' '.join([w.capitalize() for w in next_line.split()])
                    child_fio = f"{surname} {rest}"
                    break
                # Next line has 1 word = just name (no patronymic)
                elif re.match(r'^[А-ЯЁҚҒҮҰҺІӘҢӨ]+$', next_line) and len(next_line) > 2:
                    surname = line.capitalize()
                    name = next_line.capitalize()
                    child_fio = f"{surname} {name}"
                    break

    if child_fio:
        result['child_fio'] = child_fio

    return result


def is_pdf(data):
    return data[:4] == b'%PDF'


def file_to_text(data, api_key):
    """Extract text from PDF or image bytes"""
    if is_pdf(data):
        return pdf_to_text(data, api_key)
    else:
        # It's an image — send directly to Vision API
        img_b64 = base64.b64encode(data).decode("utf-8")
        return ocr_with_google_vision(img_b64, api_key)


def extract_from_pdfs(parent_bytes, child_bytes, api_key):
    result = {}
    try:
        parent_text = file_to_text(parent_bytes, api_key)
        logger.info(f"Parent text: {parent_text[:300]}")
        result.update(parse_parent_fields(parent_text))
    except Exception as e:
        logger.error(f"Parent file error: {e}")
    try:
        child_text = file_to_text(child_bytes, api_key)
        logger.info(f"Child text: {child_text[:300]}")
        result.update(parse_child_fields(child_text))
    except Exception as e:
        logger.error(f"Child file error: {e}")
    return result
