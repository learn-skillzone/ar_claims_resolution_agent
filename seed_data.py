import os
from datetime import datetime, timedelta
import chromadb
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv
from db.database import init_db, get_connection, DB_PATH
from agents.workflow import get_embedding_function

load_dotenv()

CHROMA_PATH = os.path.join(os.path.dirname(__file__), "db", "chroma_store")
SAMPLE_DIR = os.path.join(os.path.dirname(__file__), "sample_data")


def seed_sqlite():
    init_db()
    conn = get_connection()
    cur = conn.cursor()

    for tbl in [
        "supplier_dispute_responses",
        "discrepancy_justifications",
        "claim_line_items",
        "claims_header",
        "erp_goods_receipts",
        "erp_purchase_orders",
        "erp_suppliers",
    ]:
        cur.execute(f"DELETE FROM {tbl}")

    suppliers = [
        ("SUP-101", "Apex Industrial Components Ltd.", "FOB Destination", "Net 30", "ar-disputes@apexind.example.com"),
        ("SUP-102", "Global Logistics & Freight Corp", "DDP Warehouse", "Net 45", "billing@globallogistics.example.com"),
        ("SUP-103", "Precision Fasteners & Hardware", "EXW Factory", "Net 30", "claims@precisionfasteners.example.com"),
    ]
    cur.executemany("INSERT INTO erp_suppliers VALUES (?, ?, ?, ?, ?)", suppliers)

    pos = [
        ("PO-45001", 1, "SUP-101", "SKU-BRG-500", "Heavy-Duty Industrial Bearings", 100, 50.00),
        ("PO-45001", 2, "SUP-101", "SKU-VLV-210", "Hydraulic Control Valves", 25, 100.00),
        ("PO-45002", 1, "SUP-102", "SKU-FRT-100", "LTL Palletized Freight Service", 10, 450.00),
        ("PO-45003", 1, "SUP-103", "SKU-BLT-880", "Titanium Flange Bolts (Box of 500)", 40, 120.00),
    ]
    cur.executemany("INSERT INTO erp_purchase_orders VALUES (?, ?, ?, ?, ?, ?, ?)", pos)

    grns = [
        (
            "GRN-9001",
            "PO-45001",
            "SKU-BRG-500",
            92,
            8,
            "8 units arrived with crushed casing and water damage; rejected at Dock 4.",
            (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d"),
        ),
        (
            "GRN-9001",
            "PO-45001",
            "SKU-VLV-210",
            25,
            0,
            "All 25 units inspected and accepted in good condition.",
            (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d"),
        ),
        (
            "GRN-9002",
            "PO-45002",
            "SKU-FRT-100",
            10,
            0,
            "10 pallet shipments delivered on schedule.",
            (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d"),
        ),
        (
            "GRN-9003",
            "PO-45003",
            "SKU-BLT-880",
            40,
            0,
            "40 boxes received intact.",
            (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
        ),
    ]
    cur.executemany("INSERT INTO erp_goods_receipts VALUES (?, ?, ?, ?, ?, ?, ?)", grns)

    t1 = (datetime.now() - timedelta(days=2, hours=4)).isoformat()
    t2 = (datetime.now() - timedelta(days=1, hours=6)).isoformat()
    t3 = (datetime.now() - timedelta(hours=5)).isoformat()

    claims = [
        (
            "CLM-2026-001",
            "SUP-103",
            "INV-88301",
            "PO-45003",
            "EDI",
            "ISA*00*...~BIG*20261126*INV-88301**PO-45003~IT1*1*40*EA*120.00**SKU-BLT-880~",
            4800.00,
            4800.00,
            "AUTO_APPROVED",
            t1,
            t1,
        ),
        (
            "CLM-2026-002",
            "SUP-101",
            "INV-2026-995",
            "PO-45001",
            "XML",
            "<Invoice><InvoiceNumber>INV-2026-995</InvoiceNumber><PONumber>PO-45001</PONumber></Invoice>",
            6250.00,
            5600.00,
            "DISCREPANCY_REVIEW",
            t2,
            None,
        ),
        (
            "CLM-2026-003",
            "SUP-102",
            "INV-FRT-774",
            "PO-45002",
            "PDF",
            "Invoice INV-FRT-774 for PO-45002: 10x SKU-FRT-100 @ $485.00 = $4,850.00 (includes fuel surcharge).",
            4850.00,
            4500.00,
            "DISCREPANCY_REVIEW",
            t3,
            None,
        ),
    ]
    cur.executemany("INSERT INTO claims_header VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", claims)

    line_items = [
        ("CLM-2026-001", "SKU-BLT-880", 40, 40, 40, 120.00, 120.00, 0.00, "MATCH_OK"),
        ("CLM-2026-002", "SKU-BRG-500", 100, 100, 92, 50.00, 50.00, -400.00, "ERR_GRN_QTY_SHORTAGE"),
        ("CLM-2026-002", "SKU-VLV-210", 25, 25, 25, 110.00, 100.00, -250.00, "ERR_PRICE_VAR_EXCEEDED"),
        ("CLM-2026-003", "SKU-FRT-100", 10, 10, 10, 485.00, 450.00, -350.00, "ERR_PRICE_VAR_EXCEEDED"),
    ]
    cur.executemany(
        """INSERT INTO claim_line_items
           (claim_id, sku, claimed_qty, erp_po_qty, erp_grn_qty, claimed_unit_price, erp_unit_price, variance_amount, discrepancy_code)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        line_items,
    )

    justifications = [
        (
            "CLM-2026-001",
            "MATCH_OK",
            "N/A - Full 3-Way Match",
            "Invoice INV-88301 matched Purchase Order PO-45003 and Goods Receipt GRN-9003 with zero variance. Approved for full settlement of $4,800.00.",
            "Auto-approved by STP rule.",
            1,
        ),
        (
            "CLM-2026-002",
            "ERR_GRN_QTY_SHORTAGE (GRN=92 vs INV=100); ERR_PRICE_VAR_EXCEEDED (PO=$100.00 vs INV=$110.00)",
            "Master Supply Agreement (Apex Industrial, Sec 4.2 - FOB Destination & Pricing): Title and risk of loss remain with Supplier until undamaged delivery at Buyer's dock. Unit prices are locked per Purchase Order.",
            "Thank you for submitting Invoice #INV-2026-995 referencing Purchase Order PO-45001. We have completed our 3-way verification and approved a settlement of $5,600.00 out of your claimed $6,250.00 (a net adjustment of $650.00).\n\nReason for Adjustment:\n• Quantity Adjustment (SKU-BRG-500): You billed for 100 units, whereas our warehouse received 92 units in good condition (8 units arrived with crushed casing and were rejected at Dock 4).\n• Unit Price Adjustment (SKU-VLV-210): The billed rate of $110.00 per unit exceeds our contracted Purchase Order price of $100.00 by $10.00 per unit.\n\nContractual Basis:\nPer Master Supply Agreement Sec 4.2 (FOB Destination), damaged goods rejected upon dock inspection are non-billable, and unit rates are governed by the executed Purchase Order.",
            "Pending analyst review.",
            0,
        ),
        (
            "CLM-2026-003",
            "ERR_PRICE_VAR_EXCEEDED (PO=$450.00 vs INV=$485.00)",
            "Freight Services Agreement (Global Logistics, Sec 7.1 - Fuel Surcharges): Contracted LTL pallet rate of $450.00 is all-inclusive unless a written rate addendum is executed prior to dispatch.",
            "Thank you for submitting Invoice #INV-FRT-774 for Purchase Order PO-45002. We have approved $4,500.00 out of your billed $4,850.00 (a net adjustment of $350.00).\n\nReason for Adjustment:\n• Unit Price Adjustment (SKU-FRT-100): Each pallet shipment was billed at $485.00 instead of the contracted Purchase Order rate of $450.00 ($35.00/pallet variance across 10 pallets).\n\nContractual Basis:\nPer Freight Services Agreement Sec 7.1, fuel surcharges require a pre-approved written addendum.",
            "Pending analyst review.",
            0,
        ),
    ]
    cur.executemany("INSERT INTO discrepancy_justifications VALUES (?, ?, ?, ?, ?, ?)", justifications)

    conn.commit()
    conn.close()
    print(f"[OK] SQLite ERP & Claims database seeded at: {DB_PATH}")


def seed_chromadb():
    os.makedirs(CHROMA_PATH, exist_ok=True)
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    ef = get_embedding_function()

    try:
        client.delete_collection("supplier_contracts")
    except Exception:
        pass

    collection = client.create_collection(name="supplier_contracts", embedding_function=ef)

    clauses = [
        {
            "id": "clause-apex-fob",
            "supplier_id": "SUP-101",
            "text": "Master Supply Agreement (Apex Industrial, Sec 4.2 - FOB Destination & Damaged Goods): Under FOB Destination terms, Seller bears all risk of loss or transit damage until goods are inspected and signed for at Buyer's receiving dock. Damaged units rejected on Goods Receipt Notes (GRN) shall be deducted from invoice settlement.",
        },
        {
            "id": "clause-apex-price",
            "supplier_id": "SUP-101",
            "text": "Master Supply Agreement (Apex Industrial, Sec 3.1 - Price Protection): All invoices must reflect the exact unit price specified on the accepted Purchase Order. Unilateral price increases without a signed PO revision are automatically adjusted to the PO unit price.",
        },
        {
            "id": "clause-global-freight",
            "supplier_id": "SUP-102",
            "text": "Freight Services Agreement (Global Logistics, Sec 7.1 - All-Inclusive Rates): Contracted per-pallet freight rates on Purchase Orders include standard fuel and handling fees. Unapproved surcharges or unlisted SKUs are ineligible for settlement without a signed rate addendum.",
        },
        {
            "id": "clause-precision-exw",
            "supplier_id": "SUP-103",
            "text": "Component Supply Terms (Precision Fasteners, Sec 5.0 - EXW Factory): Risk of loss transfers upon carrier pickup at Seller's dock, provided packaging meets ISO-9001 export standards.",
        },
    ]

    collection.add(
        ids=[c["id"] for c in clauses],
        documents=[c["text"] for c in clauses],
        metadatas=[{"supplier_id": c["supplier_id"]} for c in clauses],
    )
    print(f"[OK] ChromaDB vector store seeded with supplier contracts at: {CHROMA_PATH}")


def create_sample_files():
    os.makedirs(SAMPLE_DIR, exist_ok=True)

    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<ClaimInvoice>
    <Header>
        <InvoiceNumber>INV-2026-995</InvoiceNumber>
        <SupplierID>SUP-101</SupplierID>
        <PONumber>PO-45001</PONumber>
    </Header>
    <LineItems>
        <Item>
            <SKU>SKU-BRG-500</SKU>
            <Quantity>100</Quantity>
            <UnitPrice>50.00</UnitPrice>
        </Item>
        <Item>
            <SKU>SKU-VLV-210</SKU>
            <Quantity>25</Quantity>
            <UnitPrice>110.00</UnitPrice>
        </Item>
    </LineItems>
</ClaimInvoice>
"""
    with open(os.path.join(SAMPLE_DIR, "claim_apex_damaged_qty.xml"), "w", encoding="utf-8") as f:
        f.write(xml_content)

    edi_content = (
        "ISA*00*          *00*          *ZZ*PRECISION      *ZZ*BUYERCORP      *261128*1030*U*00401*000000101*0*P*>~"
        "GS*IN*PRECISION*BUYERCORP*20261128*1030*101*X*004010~"
        "ST*810*0001~"
        "BIG*20261128*INV-88305**PO-45003~"
        "N1*SE*Precision Fasteners*92*SUP-103~"
        "IT1*1*40*EA*120.00**SKU-BLT-880~"
        "TDS*480000~"
        "SE*6*0001~"
        "GE*1*101~"
        "IEA*1*000000101~"
    )
    with open(os.path.join(SAMPLE_DIR, "claim_precision_clean.edi"), "w", encoding="utf-8") as f:
        f.write(edi_content)

    width, height = 1000, 1280
    img = Image.new("RGB", (width, height), color=(250, 249, 246))
    draw = ImageDraw.Draw(img)
    draw.rectangle([30, 30, width - 30, height - 30], outline=(180, 180, 180), width=2)
    font_title = ImageFont.load_default()
    font_bold = font_title
    font_reg = font_title

    draw.text((65, 65), "GLOBAL LOGISTICS & FREIGHT CORP", fill=(20, 35, 60), font=font_title)
    draw.text((65, 110), "Supplier ID: SUP-102  |  1400 Harbor Way, Newark, NJ", fill=(80, 80, 80), font=font_reg)
    draw.text((660, 65), "TAX INVOICE", fill=(180, 40, 40), font=font_title)
    draw.text((660, 110), "Invoice Number: INV-2026-4410", fill=(20, 20, 20), font=font_bold)
    draw.text((660, 138), "PO Number: PO-45002", fill=(20, 20, 20), font=font_bold)

    y_table = 350
    draw.rectangle([65, y_table, width - 65, y_table + 42], fill=(230, 235, 242))
    draw.text((80, y_table + 11), "Item SKU", fill=(20, 20, 20), font=font_bold)
    draw.text((280, y_table + 11), "Description", fill=(20, 20, 20), font=font_bold)
    draw.text((590, y_table + 11), "Qty", fill=(20, 20, 20), font=font_bold)
    draw.text((690, y_table + 11), "Unit Price", fill=(20, 20, 20), font=font_bold)
    draw.text((830, y_table + 11), "Line Total", fill=(20, 20, 20), font=font_bold)

    y_row1 = y_table + 58
    draw.text((80, y_row1), "SKU-PALLET-09", fill=(20, 20, 20), font=font_reg)
    draw.text((280, y_row1), "Reinforced Shipping Pallets", fill=(20, 20, 20), font=font_reg)
    draw.text((595, y_row1), "50", fill=(20, 20, 20), font=font_reg)
    draw.text((695, y_row1), "$95.00", fill=(20, 20, 20), font=font_reg)
    draw.text((830, y_row1), "$4,750.00", fill=(20, 20, 20), font=font_reg)

    draw.text((660, y_row1 + 85), "TOTAL CLAIMED AMOUNT:", fill=(20, 20, 20), font=font_bold)
    draw.text((830, y_row1 + 118), "$4,750.00", fill=(20, 35, 60), font=font_title)

    img.save(os.path.join(SAMPLE_DIR, "sample_ocr_invoice.png"))
    print(f"[OK] Sample XML, EDI, and OCR files generated in {SAMPLE_DIR}")


if __name__ == "__main__":
    seed_sqlite()
    seed_chromadb()
    create_sample_files()