import os
import json
import pandas as pd
from langchain_openai import ChatOpenAI
from db.repository import get_consistent_explanation


def generate_supplier_assistant_reply(
    user_question: str,
    claim_row: pd.Series,
    lines_df: pd.DataFrame,
    just_data: dict,
) -> str:
    use_mock = os.getenv("USE_MOCK_LLM", "true").lower() == "true"
    discrepancy_amt = float(claim_row["total_claimed_amount"]) - float(
        claim_row["total_approved_amount"]
    )
    clause = just_data.get(
        "rag_contract_clause",
        "Settlement is governed by verified warehouse GRN quantities and contracted PO unit prices.",
    )
    explanation = get_consistent_explanation(claim_row, just_data)

    if not use_mock and os.getenv("OPENAI_API_KEY"):
        llm = ChatOpenAI(model=os.getenv("LLM_MODEL", "gpt-4o-mini"), temperature=0.2)
        line_records = lines_df[
            [
                "sku",
                "claimed_qty",
                "erp_po_qty",
                "erp_grn_qty",
                "claimed_unit_price",
                "erp_unit_price",
                "variance_amount",
                "discrepancy_code",
            ]
        ].to_dict(orient="records")

        prompt = f"""You are an AI Accounts Receivable Dispute Assistant helping a supplier understand a discrepancy on their invoice.
Answer clearly, politely, and concisely using ONLY the verified claim data below. Never invent approvals or alter figures.
If the supplier wants to formally dispute the adjustment or submit proof, instruct them to post their explanation and supporting document (e.g., signed POD, Bill of Lading, or rate addendum) in the 'Claim Audit Thread & Supporting Proof' section right below.

Invoice Number: {claim_row['invoice_number']}
PO Number: {claim_row['po_number']}
Status: {claim_row['status']}
Incoterms: {claim_row.get('incoterms', 'N/A')}
Billed Amount: ${float(claim_row['total_claimed_amount']):,.2f}
Approved Settlement: ${float(claim_row['total_approved_amount']):,.2f}
Discrepancy / Deduction: ${discrepancy_amt:,.2f}

Line-Item Breakdown:
{json.dumps(line_records, indent=2)}

Governing Contract Clause:
{clause}

Official Adjustment Notice:
{explanation}

Supplier Question: {user_question}
"""
        return llm.invoke(prompt).content.strip()

    q = user_question.lower()
    discrepant_lines = lines_df[lines_df["variance_amount"] != 0]

    if any(w in q for w in ["contract", "clause", "policy", "incoterm", "rule", "terms"]):
        return (
            f"**Governing Policy & Incoterms ({claim_row.get('incoterms', 'Standard Terms')}):**\n\n"
            f"> {clause}\n\n"
            "If you have documentation showing compliance with this clause, attach it in the **Claim Audit Thread** below."
        )

    if any(w in q for w in ["proof", "document", "upload", "dispute", "contest", "override", "how"]):
        return (
            f"To formally contest the **${discrepancy_amt:,.2f}** adjustment on Invoice `{claim_row['invoice_number']}`, "
            "submit a message in the **Claim Audit Thread & Supporting Proof** panel below with:\n"
            "1. A brief explanation referencing the disputed SKU(s).\n"
            "2. Supporting proof (such as a carrier-signed **Proof of Delivery / BOL** for quantity shortages, or a signed **Rate Addendum** for price variances).\n\n"
            "Your submission immediately flags the claim for an AR Specialist to review."
        )

    if discrepant_lines.empty:
        line_summary = f"• Full invoice adjustment of **${discrepancy_amt:,.2f}** under status `{claim_row['status']}`."
    else:
        bullets = []
        for _, r in discrepant_lines.iterrows():
            bullets.append(
                f"• **{r['sku']}**: Billed `{int(r['claimed_qty'])}` @ `${float(r['claimed_unit_price']):,.2f}` vs. "
                f"Accepted GRN `{int(r['erp_grn_qty'])}` @ PO rate `${float(r['erp_unit_price']):,.2f}` "
                f"(Adjustment: `${float(r['variance_amount']):,.2f}`)"
            )
        line_summary = "\n".join(bullets)

    return (
        f"Here is the exact breakdown for **Invoice `{claim_row['invoice_number']}`** (PO `{claim_row['po_number']}`):\n\n"
        f"• **Billed:** `${float(claim_row['total_claimed_amount']):,.2f}` | "
        f"**Approved:** `${float(claim_row['total_approved_amount']):,.2f}` | "
        f"**Deduction:** `${discrepancy_amt:,.2f}`\n\n"
        f"**Line-Item Variances:**\n{line_summary}\n\n"
        f"**Contractual Basis:** {clause}\n\n"
        "If you disagree with these figures, post your rebuttal and attach supporting proof in the **Claim Audit Thread** below."
    )
