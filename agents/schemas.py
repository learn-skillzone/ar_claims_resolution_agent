from typing import List
from pydantic import BaseModel, Field


class ExtractedLineItem(BaseModel):
    sku: str = Field(..., description="Product SKU code")
    claimed_qty: int = Field(..., description="Quantity billed by supplier")
    claimed_unit_price: float = Field(..., description="Unit price billed by supplier")


class CanonicalClaim(BaseModel):
    invoice_number: str = Field(..., description="Supplier Invoice ID")
    supplier_id: str = Field(..., description="Supplier Vendor ID (e.g. SUP-101)")
    po_number: str = Field(..., description="Referenced Purchase Order number")
    file_format: str = Field(default="UNKNOWN", description="Source file format")
    line_items: List[ExtractedLineItem] = Field(default_factory=list)


class LineDiscrepancyResult(BaseModel):
    sku: str
    claimed_qty: int
    erp_po_qty: int
    erp_grn_qty: int
    claimed_unit_price: float
    erp_unit_price: float
    approved_line_amount: float
    variance_amount: float
    discrepancy_code: str
    erp_detail: str
