import streamlit as st
from db.repository import (
    load_claims_df,
    load_line_items_df,
    load_justification,
    get_consistent_explanation,
    load_supplier_responses,
    post_audit_thread_entry,
)
from agents.assistant import generate_supplier_assistant_reply


def render_supplier_portal() -> None:
    supplier_id = st.session_state.user_id
    supplier_name = st.session_state.user_name

    st.header(f"Discrepancy & Settlement Portal — {supplier_name} (`{supplier_id}`)")
    st.write(
        "Review discrepant invoices, ask our AI Dispute Assistant about any line-item or contract rule, "
        "and collaborate with our AR team via the claim audit thread."
    )

    df_all_claims = load_claims_df()
    discrepant_statuses = [
        "DISCREPANCY_REVIEW",
        "APPROVED_WITH_ADJUSTMENT",
        "DISPUTED_BY_SUPPLIER",
        "REJECTED",
    ]

    discrepant_claims = df_all_claims[
        (df_all_claims["supplier_id"] == supplier_id)
        & (
            (df_all_claims["total_claimed_amount"] > df_all_claims["total_approved_amount"])
            | (df_all_claims["status"].isin(discrepant_statuses))
        )
    ].copy()

    if discrepant_claims.empty:
        st.success(
            f"No discrepant invoices found for **{supplier_name}** (`{supplier_id}`). "
            "All your processed invoices are currently in good standing."
        )
        return

    discrepant_claims["discrepancy_amount"] = (
        discrepant_claims["total_claimed_amount"] - discrepant_claims["total_approved_amount"]
    )

    status_map = {
        "AUTO_APPROVED": "✅ Approved for Full Payment",
        "APPROVED_WITH_ADJUSTMENT": "⚖️ Partially Approved (Adjusted)",
        "DISCREPANCY_REVIEW": "⏳ Under AR Review (Adjustment Pending)",
        "DISPUTED_BY_SUPPLIER": "📩 Counter-Proof Under Review",
        "REJECTED": "❌ Rejected",
    }
    discrepant_claims["friendly_status"] = discrepant_claims["status"].map(
        lambda s: status_map.get(s, s)
    )

    st.subheader(f"Invoices with Discrepancies ({len(discrepant_claims)} found)")
    overview_cols = [
        "invoice_number",
        "po_number",
        "total_claimed_amount",
        "total_approved_amount",
        "discrepancy_amount",
        "friendly_status",
        "created_at",
    ]
    overview_df = discrepant_claims[overview_cols].copy()
    overview_df.columns = [
        "Invoice Number",
        "PO Reference",
        "Billed Amount ($)",
        "Approved Amount ($)",
        "Discrepancy ($)",
        "Status",
        "Submitted Date",
    ]
    st.dataframe(overview_df, use_container_width=True, hide_index=True)

    invoice_options = [
        f"{row['invoice_number']} | PO: {row['po_number']} | Discrepancy: ${row['discrepancy_amount']:,.2f} ({row['friendly_status']})"
        for _, row in discrepant_claims.iterrows()
    ]
    selected_inv_label = st.selectbox(
        "Select an Invoice Number for Full Details, AI Assistance & Audit Thread:",
        invoice_options,
    )
    selected_invoice_num = selected_inv_label.split(" | ")[0]

    sup_claim = discrepant_claims[
        discrepant_claims["invoice_number"] == selected_invoice_num
    ].iloc[0]
    sup_claim_id = sup_claim["claim_id"]
    sup_lines = load_line_items_df(sup_claim_id)
    sup_just = load_justification(sup_claim_id)
    consistent_explanation = get_consistent_explanation(sup_claim, sup_just)
    thread_df = load_supplier_responses(sup_claim_id)

    st.divider()
    st.subheader(
        f"Discrepancy Details — Invoice `{sup_claim['invoice_number']}` (PO `{sup_claim['po_number']}`)"
    )

    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Current Status", sup_claim["friendly_status"])
    s2.metric("Billed Amount", f"${sup_claim['total_claimed_amount']:,.2f}")
    s3.metric("Approved Settlement", f"${sup_claim['total_approved_amount']:,.2f}")
    s4.metric("Discrepancy / Deduction", f"${sup_claim['discrepancy_amount']:,.2f}")

    st.subheader("Plain-Language Discrepancy Explanation")
    st.info(
        consistent_explanation
        or "Adjustment details are currently being reviewed by our Accounts Receivable team."
    )

    st.subheader("Line-Item Settlement Breakdown")
    sup_line_cols = [
        "sku",
        "claimed_qty",
        "erp_grn_qty",
        "claimed_unit_price",
        "erp_unit_price",
        "variance_amount",
    ]
    supplier_table = sup_lines[sup_line_cols].copy()
    supplier_table.columns = [
        "Item SKU",
        "Billed Qty",
        "Accepted Warehouse Qty",
        "Billed Unit Price ($)",
        "Contracted Price ($)",
        "Adjustment ($)",
    ]
    st.dataframe(supplier_table, use_container_width=True, hide_index=True)

    st.divider()
    col_ai, col_thread = st.columns([1.05, 1.15])

    with col_ai:
        st.subheader("🤖 AI Dispute Assistant (Instant Q&A)")
        st.caption(
            f"Ask questions about Invoice `{sup_claim['invoice_number']}`, SKU variances, or contract terms."
        )

        if sup_claim_id not in st.session_state.supplier_ai_chats:
            st.session_state.supplier_ai_chats[sup_claim_id] = [
                {
                    "role": "assistant",
                    "content": (
                        f"Hi **{supplier_name}**! I have the full 3-way match breakdown and contract terms for "
                        f"**Invoice `{sup_claim['invoice_number']}`** loaded. Ask me why an item was adjusted "
                        "or what supporting proof is needed to contest the deduction."
                    ),
                }
            ]

        q_col1, q_col2 = st.columns(2)
        quick_prompt = None
        if q_col1.button(
            "Why was this adjusted?",
            key=f"qp_why_{sup_claim_id}",
            use_container_width=True,
        ):
            quick_prompt = "Why was this invoice adjusted? Break down the exact line-item differences."
        if q_col2.button(
            "What proof do I need?",
            key=f"qp_proof_{sup_claim_id}",
            use_container_width=True,
        ):
            quick_prompt = "What supporting documents do I need to upload to contest this deduction?"

        chat_box = st.container(height=310, border=True)
        with chat_box:
            for msg in st.session_state.supplier_ai_chats[sup_claim_id]:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

        user_q = st.chat_input(
            f"Ask about Invoice {sup_claim['invoice_number']}...",
            key=f"chat_input_{sup_claim_id}",
        )
        active_prompt = quick_prompt or user_q

        if active_prompt:
            st.session_state.supplier_ai_chats[sup_claim_id].append(
                {"role": "user", "content": active_prompt}
            )
            ai_reply = generate_supplier_assistant_reply(
                active_prompt, sup_claim, sup_lines, sup_just
            )
            st.session_state.supplier_ai_chats[sup_claim_id].append(
                {"role": "assistant", "content": ai_reply}
            )
            st.rerun()

    with col_thread:
        st.subheader("📩 Claim Audit Thread & Supporting Proof")
        st.caption(
            "Two-way evidentiary log with the Accounts Receivable team (permanently tied to this claim)."
        )

        audit_box = st.container(height=230, border=True)
        with audit_box:
            if thread_df.empty:
                st.info(
                    "No messages or counter-proof submitted on this claim yet. Use the form below to submit proof or reply to AR."
                )
            else:
                for _, entry in thread_df.iterrows():
                    role_label = entry.get("sender_role") or "Supplier"
                    sender_label = entry.get("sender_name") or supplier_name
                    ts_label = str(entry["submitted_at"])[:16].replace("T", " ")
                    is_agent = role_label == "Claim Processing Agent"
                    badge = "🛡️ AR Specialist" if is_agent else "🏢 Supplier"

                    with st.chat_message("assistant" if is_agent else "user"):
                        st.markdown(
                            f"**{badge} ({sender_label})** · `{ts_label}`\n\n"
                            f"{entry['supplier_comment']}"
                        )
                        if entry.get("proof_filename"):
                            st.caption(f"📎 Attached Document: `{entry['proof_filename']}`")

        with st.form(key=f"supplier_dispute_form_{sup_claim_id}"):
            comment = st.text_area(
                "Post a message or rebuttal to AR Team:",
                height=90,
                placeholder="Example: Attached is the signed POD showing all units left our dock undamaged...",
            )
            proof_file = st.file_uploader(
                "Attach Supporting Document (Signed POD, Bill of Lading, Rate Addendum)",
                type=["pdf", "png", "jpg", "jpeg"],
            )
            submit_dispute = st.form_submit_button(
                "Post to Claim Audit Thread", type="primary", use_container_width=True
            )

            if submit_dispute:
                if not comment.strip():
                    st.error("Please enter a message before posting.")
                else:
                    post_audit_thread_entry(
                        claim_id=sup_claim_id,
                        supplier_id=supplier_id,
                        sender_role="Supplier",
                        sender_name=supplier_name,
                        comment=comment,
                        proof_filename=proof_file.name if proof_file else None,
                        mark_disputed=True,
                    )
                    st.success(
                        "Message and proof posted to the Claim Audit Thread and flagged for AR Specialist review."
                    )
                    st.rerun()
