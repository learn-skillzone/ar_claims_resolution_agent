import os
from PIL import Image, ImageDraw, ImageFont

os.makedirs("sample_data", exist_ok=True)

# Create an A4-proportioned off-white "scanned paper" canvas
width, height = 1000, 1280
img = Image.new("RGB", (width, height), color=(250, 249, 246))
draw = ImageDraw.Draw(img)

# Outer scan border
draw.rectangle([30, 30, width - 30, height - 30], outline=(180, 180, 180), width=2)

try:
    font_title = ImageFont.truetype("arial.ttf", 30)
    font_bold = ImageFont.truetype("arialbd.ttf", 19)
    font_reg = ImageFont.truetype("arial.ttf", 18)
except OSError:
    font_title = ImageFont.load_default()
    font_bold = font_title
    font_reg = font_title

# Header block
draw.text((65, 65), "GLOBAL LOGISTICS & FREIGHT CORP", fill=(20, 35, 60), font=font_title)
draw.text((65, 110), "Supplier ID: SUP-102  |  1400 Harbor Way, Newark, NJ", fill=(80, 80, 80), font=font_reg)

draw.text((660, 65), "TAX INVOICE", fill=(180, 40, 40), font=font_title)
draw.text((660, 110), "Invoice Number: INV-2026-4410", fill=(20, 20, 20), font=font_bold)
draw.text((660, 138), "PO Number: PO-45002", fill=(20, 20, 20), font=font_bold)
draw.text((660, 166), "Invoice Date: 2026-11-28", fill=(60, 60, 60), font=font_reg)

draw.line([(65, 210), (width - 65, 210)], fill=(120, 120, 120), width=2)

# Bill-To section
draw.text((65, 230), "BILL TO:", fill=(80, 80, 80), font=font_bold)
draw.text((65, 258), "Accounts Receivable & Procurement Operations", fill=(30, 30, 30), font=font_reg)
draw.text((65, 284), "Incoterms: FOB Destination", fill=(30, 30, 30), font=font_reg)

# Line Items Table Header
y_table = 350
draw.rectangle([65, y_table, width - 65, y_table + 42], fill=(230, 235, 242))
draw.text((80, y_table + 11), "Item SKU", fill=(20, 20, 20), font=font_bold)
draw.text((280, y_table + 11), "Description", fill=(20, 20, 20), font=font_bold)
draw.text((590, y_table + 11), "Qty", fill=(20, 20, 20), font=font_bold)
draw.text((690, y_table + 11), "Unit Price", fill=(20, 20, 20), font=font_bold)
draw.text((830, y_table + 11), "Line Total", fill=(20, 20, 20), font=font_bold)

# Line Item 1 (Matches PO or triggers price/qty variance depending on seed_data)
y_row1 = y_table + 58
draw.text((80, y_row1), "SKU-PALLET-09", fill=(20, 20, 20), font=font_reg)
draw.text((280, y_row1), "Heavy-Duty Reinforced Shipping Pallets", fill=(20, 20, 20), font=font_reg)
draw.text((595, y_row1), "50", fill=(20, 20, 20), font=font_reg)
draw.text((695, y_row1), "$95.00", fill=(20, 20, 20), font=font_reg)
draw.text((830, y_row1), "$4,750.00", fill=(20, 20, 20), font=font_reg)

draw.line([(65, y_row1 + 45), (width - 65, y_row1 + 45)], fill=(200, 200, 200), width=1)

# Totals
draw.text((660, y_row1 + 85), "TOTAL CLAIMED AMOUNT:", fill=(20, 20, 20), font=font_bold)
draw.text((830, y_row1 + 118), "$4,750.00", fill=(20, 35, 60), font=font_title)

# Simulated "RECEIVED / SCANNED" stamp
draw.rectangle([90, 620, 360, 690], outline=(34, 139, 34), width=3)
draw.text((112, 643), "SCANNED COPY - AR INTAKE", fill=(34, 139, 34), font=font_bold)

# Slight 0.6-degree rotation to mimic a real flatbed scanner
scanned = img.rotate(0.6, resample=Image.BICUBIC, expand=False, fillcolor=(245, 245, 245))
out_path = os.path.join("sample_data", "sample_ocr_invoice.png")
scanned.save(out_path)
print(f"[OK] Generated sample OCR invoice at: {out_path}")