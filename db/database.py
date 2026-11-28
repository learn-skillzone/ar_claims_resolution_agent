import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "ar_claims.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute('''
        CREATE TABLE IF NOT EXISTS erp_suppliers (
            supplier_id TEXT PRIMARY KEY,
            supplier_name TEXT NOT NULL,
            incoterms TEXT NOT NULL,
            payment_terms TEXT NOT NULL,
            contact_email TEXT NOT NULL
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS erp_purchase_orders (
            po_number TEXT NOT NULL,
            line_num INTEGER NOT NULL,
            supplier_id TEXT NOT NULL,
            sku TEXT NOT NULL,
            description TEXT,
            ordered_qty INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            PRIMARY KEY (po_number, line_num)
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS erp_goods_receipts (
            grn_number TEXT NOT NULL,
            po_number TEXT NOT NULL,
            sku TEXT NOT NULL,
            received_good_qty INTEGER NOT NULL,
            damaged_qty INTEGER DEFAULT 0,
            receiving_notes TEXT,
            received_date TEXT
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS claims_header (
            claim_id TEXT PRIMARY KEY,
            supplier_id TEXT NOT NULL,
            invoice_number TEXT NOT NULL,
            po_number TEXT NOT NULL,
            file_format TEXT NOT NULL,
            raw_content TEXT,
            total_claimed_amount REAL NOT NULL,
            total_approved_amount REAL DEFAULT 0.0,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            resolved_at TEXT
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS claim_line_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            claim_id TEXT NOT NULL,
            sku TEXT NOT NULL,
            claimed_qty INTEGER NOT NULL,
            erp_po_qty INTEGER,
            erp_grn_qty INTEGER,
            claimed_unit_price REAL NOT NULL,
            erp_unit_price REAL,
            variance_amount REAL DEFAULT 0.0,
            discrepancy_code TEXT,
            FOREIGN KEY (claim_id) REFERENCES claims_header(claim_id)
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS discrepancy_justifications (
            claim_id TEXT PRIMARY KEY,
            erp_raw_codes TEXT,
            rag_contract_clause TEXT,
            natural_language_explanation TEXT,
            analyst_notes TEXT,
            approved_by_human INTEGER DEFAULT 0,
            FOREIGN KEY (claim_id) REFERENCES claims_header(claim_id)
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS supplier_dispute_responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            claim_id TEXT NOT NULL,
            supplier_id TEXT NOT NULL,
            sender_role TEXT DEFAULT 'Supplier',
            sender_name TEXT,
            supplier_comment TEXT NOT NULL,
            proof_filename TEXT,
            submitted_at TEXT NOT NULL,
            FOREIGN KEY (claim_id) REFERENCES claims_header(claim_id)
        )
    ''')

    cur.execute("PRAGMA table_info(supplier_dispute_responses)")
    existing_cols = {row[1] for row in cur.fetchall()}
    if "sender_role" not in existing_cols:
        cur.execute("ALTER TABLE supplier_dispute_responses ADD COLUMN sender_role TEXT DEFAULT 'Supplier'")
    if "sender_name" not in existing_cols:
        cur.execute("ALTER TABLE supplier_dispute_responses ADD COLUMN sender_name TEXT")

    conn.commit()
    conn.close()
