import re
import fitz  # PyMuPDF
import requests
import base64
import json
import logging

logger = logging.getLogger(__name__)

GOOGLE_VISION_URL = "https://vision.googleapis.com/v1/images:annotate"


def pdf_page_to_base64(pdf_bytes, page_num=0):
    """Convert PDF page to base64 image for Vision API"""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[page_num]
    mat = fitz.Matrix(2.0, 2.0)  # 2x zoom for better quality
    pix = page.get_pixmap(matrix=mat)
    img_bytes = pix.tobytes("png")
    return base64.b64encode(img_bytes).decode("utf-8")


def ocr_with_google_vision(image_b64, api_key):
    """Send image to Google Vision API and get text"""
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
    """Extract text from PDF — native text first, then Google Vision OCR"""
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
    """Parse parent fields from OCR text"""
    result = {}
    text_clean = re.sub(r'\s+', ' ', text)

    # IIN — 12 digits
    iins = re.findall(r'\b(\d{12})\b', text_clean)
    if iins:
        result['parent_iin'] = iins[0]

    # Document number
    doc_match = re.search(r'(?:№|N|No\.?)\s*([A-Z]{0,2}\d{7,9})', text_clean)
    if doc_match:
        result['parent_doc_num'] = doc_match.group(1)

    # Dates DD.MM.YYYY
    dates = re.findall(r'\b(\d{2}[./]\d{2}[./]\d{4})\b', text_clean)
    if dates:
        result['parent_doc_date'] = dates[0].replace('/', '.')

    # FIO — 2-3 Cyrillic capitalized words
    fio_match = re.search(r'([А-ЯЁҚҒҮҰҺІӘҢӨ][а-яёқғүұһіәңө]+\s+[А-ЯЁҚҒҮҰҺІӘҢӨ][а-яёқғүұһіәңө]+(?:\s+[А-ЯЁҚҒҮҰҺІӘҢӨ][а-яёқғүұһіәңө]+)?)', text_clean)
    if fio_match:
        result['parent_fio'] = fio_match.group(1).strip()

    # Address
    addr_match = re.search(r'(?:мекенжай|адрес|тұрғылықты)[^\n:]*[:\s]+([^\n]{10,100})', text_clean, re.IGNORECASE)
    if addr_match:
        result['parent_address'] = addr_match.group(1).strip()

    return result


def parse_child_fields(text):
    """Parse child fields from OCR text"""
    result = {}
    text_clean = re.sub(r'\s+', ' ', text)

    # IIN — 12 digits
    iins = re.findall(r'\b(\d{12})\b', text_clean)
    if iins:
        result['child_iin'] = iins[0]

    # FIO
    fio_match = re.search(r'([А-ЯЁҚҒҮҰҺІӘҢӨ][а-яёқғүұһіәңө]+\s+[А-ЯЁҚҒҮҰҺІӘҢӨ][а-яёқғүұһіәңө]+(?:\s+[А-ЯЁҚҒҮҰҺІӘҢӨ][а-яёқғүұһіәңө]+)?)', text_clean)
    if fio_match:
        result['child_fio'] = fio_match.group(1).strip()

    return result


def extract_from_pdfs(parent_bytes, child_bytes, api_key):
    """Extract all fields from both PDFs"""
    result = {}

    try:
        parent_text = pdf_to_text(parent_bytes, api_key)
        logger.info(f"Parent text: {parent_text[:300]}")
        result.update(parse_parent_fields(parent_text))
    except Exception as e:
        logger.error(f"Parent PDF error: {e}")

    try:
        child_text = pdf_to_text(child_bytes, api_key)
        logger.info(f"Child text: {child_text[:300]}")
        result.update(parse_child_fields(child_text))
    except Exception as e:
        logger.error(f"Child PDF error: {e}")

    return result
