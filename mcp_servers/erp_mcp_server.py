import json
from mcp.server.mcpserver import MCPServer
from db.database import get_connection

mcp = MCPServer("MockERPServer")


@mcp.tool()
def get_purchase_order(po_number: str) -> str:
    """Retrieve Purchase Order header and line items from ERP by PO number."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM erp_purchase_orders WHERE po_number = ?", (po_number,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    if not rows:
        return json.dumps({"found": False, "po_number": po_number, "items": []})
    return json.dumps({"found": True, "po_number": po_number, "items": rows})


@mcp.tool()
def get_goods_receipt(po_number: str) -> str:
    """Retrieve Warehouse Goods Receipt Notes (GRN) and inspection damage logs for a PO."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM erp_goods_receipts WHERE po_number = ?", (po_number,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return json.dumps({"po_number": po_number, "receipts": rows})


@mcp.tool()
def get_supplier_profile(supplier_id: str) -> str:
    """Retrieve Supplier master profile including Incoterms and Payment Terms."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM erp_suppliers WHERE supplier_id = ?", (supplier_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return json.dumps({"found": False, "supplier_id": supplier_id})
    return json.dumps({"found": True, "supplier": dict(row)})


if __name__ == "__main__":
    mcp.run()