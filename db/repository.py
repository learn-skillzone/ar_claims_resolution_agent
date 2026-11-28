from datetime import datetime
import pandas as pd
from db.database import get_connection


def load_claims_df() -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql_query(
        """
        SELECT c.*, s.supplier_name, s.incoterms
        FROM claims_header c
        LEFT JOIN erp_suppliers s ON c.supplier_id = s.supplier_id
        ORDER BY c.created_at DESC
        """,
        conn,
    )
    conn.close()
    return df


def load_line_items_df(claim_id: str | None = None) -> pd.DataFrame:
    conn = get_connection()
    if claim_id:
        df = pd.read_sql_query(
            "SELECT * FROM claim_line_items WHERE claim_id = ?",
            conn,
            params=(claim_id,),
        )
    else:
        df = pd.read_sql_query("SELECT * FROM claim_line_items", conn)
    conn.close()
    return df


def load_justification(claim_id: str) -> dict:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM discrepancy_justifications WHERE claim_id = ?",
        (claim_id,),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else {}


def get_consistent_explanation(claim_row: pd.Series, just_data: dict) -> str:
    raw_text = just_data.get("natural_language_explanation", "")
    is_rejected = str(claim_row["status"]).strip().upper() == "REJECTED"
    approved_amt = float(claim_row["total_approved_amount"])

    if is_rejected and approved_amt == 0.0:
        if "REJECTED IN FULL" not in raw_text.upper():
            supplier_label = claim_row.get("supplier_name") or claim_row["supplier_id"]
            clause = just_data.get(
                "rag_contract_clause",
                "Does not meet PO/GRN verification requirements.",
            )
            corrected_text = (
                f"Dear {supplier_label} Billing Team,\n\n"
                f"Your claim for Invoice #{claim_row['invoice_number']} (PO #{claim_row['po_number']}) "
                f"in the total amount of ${float(claim_row['total_claimed_amount']):,.2f} has been REJECTED IN FULL "
                f"($0.00 approved settlement; ${float(claim_row['total_claimed_amount']):,.2f} deducted).\n\n"
                f"Reason & Policy Basis:\n{clause}\n\n"
                f"Please review the discrepancy details below and submit a corrected invoice or supporting proof."
            )
            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                "UPDATE discrepancy_justifications SET natural_language_explanation = ? WHERE claim_id = ?",
                (corrected_text, claim_row["claim_id"]),
            )
            conn.commit()
            conn.close()
            return corrected_text

    return raw_text


def load_supplier_responses(claim_id: str) -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql_query(
        "SELECT * FROM supplier_dispute_responses WHERE claim_id = ? ORDER BY submitted_at ASC",
        conn,
        params=(claim_id,),
    )
    conn.close()
    return df


def load_suppliers_map() -> dict:
    conn = get_connection()
    df = pd.read_sql_query("SELECT supplier_id, supplier_name FROM erp_suppliers", conn)
    conn.close()
    return dict(zip(df["supplier_id"], df["supplier_name"]))


def post_audit_thread_entry(
    claim_id: str,
    supplier_id: str,
    sender_role: str,
    sender_name: str,
    comment: str,
    proof_filename: str | None = None,
    mark_disputed: bool = False,
) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO supplier_dispute_responses
           (claim_id, supplier_id, sender_role, sender_name, supplier_comment, proof_filename, submitted_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            claim_id,
            supplier_id,
            sender_role,
            sender_name,
            comment.strip(),
            proof_filename,
            datetime.now().isoformat(),
        ),
    )
    if mark_disputed:
        cur.execute(
            "UPDATE claims_header SET status = 'DISPUTED_BY_SUPPLIER' WHERE claim_id = ?",
            (claim_id,),
        )
    conn.commit()
    conn.close()


def approve_claim_with_adjustment(
    claim_id: str, explanation_text: str, agent_id: str
) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """UPDATE discrepancy_justifications
           SET natural_language_explanation = ?, approved_by_human = 1,
               analyst_notes = ?
           WHERE claim_id = ?""",
        (
            explanation_text,
            f"Approved with adjustment by {agent_id}",
            claim_id,
        ),
    )
    cur.execute(
        """UPDATE claims_header
           SET status = 'APPROVED_WITH_ADJUSTMENT', resolved_at = ?
           WHERE claim_id = ?""",
        (datetime.now().isoformat(), claim_id),
    )
    conn.commit()
    conn.close()


def reject_claim_in_full(
    claim_id: str,
    claim_row: pd.Series,
    just_data: dict,
    edited_text: str,
    display_explanation: str,
    agent_id: str,
) -> None:
    norm_edited = edited_text.replace("\r\n", "\n").strip()
    norm_initial = display_explanation.replace("\r\n", "\n").strip()

    if norm_edited and norm_edited != norm_initial and "REJECTED" in norm_edited.upper():
        rejection_explanation = edited_text
    else:
        rejection_explanation = (
            f"Dear {claim_row['supplier_name']} Billing Team,\n\n"
            f"Your claim for Invoice #{claim_row['invoice_number']} (PO #{claim_row['po_number']}) "
            f"in the total amount of ${float(claim_row['total_claimed_amount']):,.2f} has been REJECTED IN FULL "
            f"($0.00 approved settlement; ${float(claim_row['total_claimed_amount']):,.2f} deducted).\n\n"
            f"Reason & Policy Basis:\n{just_data.get('rag_contract_clause', 'Does not meet PO/GRN verification requirements.')}\n\n"
            f"Please review the discrepancy details below and submit a corrected invoice or supporting proof."
        )

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """UPDATE discrepancy_justifications
           SET natural_language_explanation = ?, approved_by_human = 1,
               analyst_notes = ?
           WHERE claim_id = ?""",
        (
            rejection_explanation,
            f"Rejected in full by {agent_id}",
            claim_id,
        ),
    )
    cur.execute(
        """UPDATE claims_header
           SET status = 'REJECTED', total_approved_amount = 0.0, resolved_at = ?
           WHERE claim_id = ?""",
        (datetime.now().isoformat(), claim_id),
    )
    conn.commit()
    conn.close()
