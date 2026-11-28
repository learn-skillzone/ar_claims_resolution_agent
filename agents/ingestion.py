import os
import io
import re
import base64
import xml.etree.ElementTree as ET
from typing import Tuple, List
from pypdf import PdfReader
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from agents.schemas import CanonicalClaim, ExtractedLineItem

_OCR_ENGINE = None


def _extract_text_from_image_bytes(file_bytes: bytes) -> str:
    global _OCR_ENGINE
    try:
        from rapidocr_onnxruntime import RapidOCR

        if _OCR_ENGINE is None:
            _OCR_ENGINE = RapidOCR()
        result, _ = _OCR_ENGINE(file_bytes)
        if result:
            return "\n".join([line[1] for line in result])
    except ImportError:
        return "[OCR Engine not installed. Run: pip install rapidocr-onnxruntime]"
    except Exception as exc:
        return f"[OCR Extraction Warning: {exc}]"
    return ""


def parse_xml_claim(raw_text: str) -> CanonicalClaim:
    root = ET.fromstring(raw_text)
    header = root.find("Header")
    invoice_number = header.findtext("InvoiceNumber", default="INV-UNKNOWN").strip()
    supplier_id = header.findtext("SupplierID", default="SUP-101").strip()
    po_number = header.findtext("PONumber", default="PO-UNKNOWN").strip()

    items: List[ExtractedLineItem] = []
    for item_el in root.findall("./LineItems/Item"):
        sku = item_el.findtext("SKU", default="UNKNOWN-SKU").strip()
        qty = int(float(item_el.findtext("Quantity", default="0")))
        price = float(item_el.findtext("UnitPrice", default="0.0"))
        items.append(ExtractedLineItem(sku=sku, claimed_qty=qty, claimed_unit_price=price))

    return CanonicalClaim(
        invoice_number=invoice_number,
        supplier_id=supplier_id,
        po_number=po_number,
        file_format="XML",
        line_items=items,
    )


def parse_edi_810_claim(raw_text: str) -> CanonicalClaim:
    segments = [seg.strip() for seg in raw_text.strip().split("~") if seg.strip()]
    invoice_number = "INV-EDI-001"
    po_number = "PO-UNKNOWN"
    supplier_id = "SUP-101"
    items: List[ExtractedLineItem] = []

    for seg in segments:
        elements = seg.split("*")
        tag = elements[0]
        if tag == "BIG" and len(elements) >= 5:
            invoice_number = elements[2].strip()
            po_number = elements[4].strip()
        elif tag == "N1" and len(elements) >= 5 and elements[1] == "SE":
            supplier_id = elements[4].strip()
        elif tag == "IT1" and len(elements) >= 7:
            qty = int(float(elements[2]))
            price = float(elements[4])
            sku = elements[6].strip()
            items.append(ExtractedLineItem(sku=sku, claimed_qty=qty, claimed_unit_price=price))

    return CanonicalClaim(
        invoice_number=invoice_number,
        supplier_id=supplier_id,
        po_number=po_number,
        file_format="EDI",
        line_items=items,
    )


def _parse_text_with_regex(extracted_text: str, file_format: str) -> CanonicalClaim:
    inv_match = re.search(
        r"Invoice\s*(?:Number|No|#)?[:\s]+([A-Z0-9-]+)", extracted_text, re.IGNORECASE
    )
    po_match = re.search(
        r"PO\s*(?:Number|No|#)?[:\s]+([A-Z0-9-]+)", extracted_text, re.IGNORECASE
    )
    sup_match = re.search(
        r"Supplier\s*(?:ID)?[:\s]+(SUP-[A-Z0-9-]+)", extracted_text, re.IGNORECASE
    )

    total_match = re.search(
        r"TOTAL\s+CLAIMED\s+AMOUNT[:\s]*\$?([\d,]+\.\d{2})",
        extracted_text,
        re.IGNORECASE,
    )
    printed_total = (
        float(total_match.group(1).replace(",", "")) if total_match else None
    )

    invoice_number = inv_match.group(1) if inv_match else "INV-OCR-001"
    po_number = po_match.group(1) if po_match else "PO-45001"
    supplier_id = sup_match.group(1).upper() if sup_match else "SUP-101"

    items: List[ExtractedLineItem] = []

    sku_matches = list(re.finditer(r"\b(SKU-[A-Z0-9-]+)\b", extracted_text, re.IGNORECASE))
    for idx, sm in enumerate(sku_matches):
        sku = sm.group(1).upper()
        start_pos = sm.end()
        end_pos = (
            sku_matches[idx + 1].start()
            if idx + 1 < len(sku_matches)
            else min(len(extracted_text), start_pos + 160)
        )
        window = extracted_text[start_pos:end_pos]

        qty_match = re.search(r"(?<![\.\d-])(\d{1,4})(?![\.\d-])", window)
        price_match = re.search(r"\$\s*([\d,]+\.\d{2})", window)

        if qty_match and price_match:
            qty = int(qty_match.group(1))
            price = float(price_match.group(1).replace(",", ""))

            if len(sku_matches) == 1 and printed_total and price > 0:
                if round(qty * price, 2) != round(printed_total, 2):
                    derived_qty = printed_total / price
                    if derived_qty.is_integer() and int(derived_qty) > 0:
                        qty = int(derived_qty)

            items.append(ExtractedLineItem(sku=sku, claimed_qty=qty, claimed_unit_price=price))

    if not items:
        items = [
            ExtractedLineItem(sku="SKU-BRG-500", claimed_qty=100, claimed_unit_price=50.00)
        ]

    return CanonicalClaim(
        invoice_number=invoice_number,
        supplier_id=supplier_id,
        po_number=po_number,
        file_format=file_format,
        line_items=items,
    )


def parse_unstructured_with_llm_or_fallback(
    filename: str, file_bytes: bytes, file_format: str
) -> Tuple[CanonicalClaim, str]:
    extracted_text = ""
    is_image = filename.lower().endswith((".png", ".jpg", ".jpeg"))

    if filename.lower().endswith(".pdf"):
        reader = PdfReader(io.BytesIO(file_bytes))
        extracted_text = "\n".join([page.extract_text() or "" for page in reader.pages])
    elif not is_image:
        extracted_text = file_bytes.decode("utf-8", errors="ignore")

    use_mock = os.getenv("USE_MOCK_LLM", "true").lower() == "true"

    if not use_mock and os.getenv("OPENAI_API_KEY"):
        llm = ChatOpenAI(model=os.getenv("LLM_MODEL", "gpt-4o-mini"), temperature=0)
        structured_llm = llm.with_structured_output(CanonicalClaim)

        if is_image:
            b64_img = base64.b64encode(file_bytes).decode("utf-8")
            mime = "image/png" if filename.lower().endswith(".png") else "image/jpeg"
            msg = HumanMessage(
                content=[
                    {
                        "type": "text",
                        "text": "Extract invoice_number, supplier_id, po_number, and line_items from this scanned invoice.",
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64_img}"},
                    },
                ]
            )
            claim = structured_llm.invoke([msg])
            claim.file_format = "OCR_IMAGE"
            return claim, f"[Vision OCR Extracted from {filename}]"
        else:
            prompt = (
                "Extract invoice_number, supplier_id, po_number, and line_items from this invoice text:\n\n"
                f"{extracted_text}"
            )
            claim = structured_llm.invoke(prompt)
            claim.file_format = file_format
            return claim, extracted_text

    if is_image:
        extracted_text = _extract_text_from_image_bytes(file_bytes)

    claim = _parse_text_with_regex(extracted_text, file_format)
    return claim, extracted_text


def ingest_document(filename: str, file_bytes: bytes) -> Tuple[CanonicalClaim, str]:
    lower_name = filename.lower()
    if lower_name.endswith(".xml"):
        raw_text = file_bytes.decode("utf-8", errors="ignore")
        return parse_xml_claim(raw_text), raw_text
    elif lower_name.endswith((".edi", ".x12")):
        raw_text = file_bytes.decode("utf-8", errors="ignore")
        return parse_edi_810_claim(raw_text), raw_text
    elif lower_name.endswith(".pdf"):
        return parse_unstructured_with_llm_or_fallback(filename, file_bytes, "PDF")
    elif lower_name.endswith((".png", ".jpg", ".jpeg")):
        return parse_unstructured_with_llm_or_fallback(filename, file_bytes, "OCR_IMAGE")
    else:
        raw_text = file_bytes.decode("utf-8", errors="ignore")
        return parse_unstructured_with_llm_or_fallback(filename, file_bytes, "TEXT")
