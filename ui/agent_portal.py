import streamlit as st
import pandas as pd
import plotly.express as px

from agents.ingestion import ingest_document
from db.repository import (
    load_claims_df,
    load_line_items_df,
    load_justification,
    get_consistent_explanation,
    load_supplier_responses,
    load_suppliers_map,
    post_audit_thread_entry,
    approve_claim_with_adjustment,
    reject_claim_in_full,
)


@st.dialog("Discrepancy Details & 3-Way Match Evidence", width="large")
def show_discrepancy_modal(claim_id: str) -> None:
    df_claims = load_claims_df()
    matched = df_claims[df_claims["claim_id"] == claim_id]
    if matched.empty:
        st.error("Claim record not found.")
        return

    claim_row = matched.iloc[0]
    lines_df = load_line_items_df(claim_id)
    just_data = load_justification(claim_id)
    sup_replies_df = load_supplier_responses(claim_id)

    st.markdown(
        f"**Claim ID:** `{claim_id}` &nbsp;|&nbsp; "
        f"**Supplier:** {claim_row['supplier_name']} (`{claim_row['supplier_id']}`) &nbsp;|&nbsp; "
        f"**Invoice:** `{claim_row['invoice_number']}` &nbsp;|&nbsp; "
        f"**PO:** `{claim_row['po_number']}`"
    )

    if not sup_replies_df.empty:
        latest_reply = sup_replies_df.iloc[-1]
        st.info(
            f"💬 **Latest Audit Thread Entry ({latest_reply.get('sender_role', 'Supplier')}):** "
            f"\"{latest_reply['supplier_comment']}\" "
            f"(Attachment: `{latest_reply['proof_filename'] or 'None'}`)"
        )

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Claimed Amount", f"${float(claim_row['total_claimed_amount']):,.2f}")
    m2.metric("ERP Approved", f"${float(claim_row['total_approved_amount']):,.2f}")
    variance = float(claim_row["total_claimed_amount"]) - float(claim_row["total_approved_amount"])
    m3.metric("Net Variance", f"${variance:,.2f}")
    m4.metric("Incoterms", claim_row["incoterms"])

    st.divider()
    st.markdown("#### 1. 3-Way Match Comparison (Claim vs. PO vs. GRN)")
    match_cols = [
        "sku",
        "claimed_qty",
        "erp_po_qty",
        "erp_grn_qty",
        "claimed_unit_price",
        "erp_unit_price",
        "variance_amount",
        "discrepancy_code",
    ]
    st.dataframe(lines_df[match_cols], use_container_width=True, hide_index=True)

    st.markdown("#### 2. ERP & Contractual Evidence")
    st.caption("Raw ERP Error Logs")
    st.code(just_data.get("erp_raw_codes", "N/A"), language="text")

    st.caption("Retrieved Contract Clause")
    st.info(just_data.get("rag_contract_clause", "N/A"))

    st.markdown("#### 3. Submitted Supplier Claim Details")
    submitted_view = lines_df[["sku", "claimed_qty", "claimed_unit_price"]].copy()
    submitted_view["claimed_line_total"] = (
        submitted_view["claimed_qty"] * submitted_view["claimed_unit_price"]
    )
    submitted_view.columns = ["SKU", "Billed Qty", "Billed Unit Price ($)", "Billed Total ($)"]
    st.dataframe(submitted_view, use_container_width=True, hide_index=True)

    st.divider()
    b_col1, b_col2 = st.columns(2)
    with b_col1:
        if st.button("⚡ Proceed to Take Action", type="primary", use_container_width=True):
            st.session_state.wb_action_claim_id = claim_id
            st.session_state.agent_active_tab = "⚖️ Analyst Discrepancy Workbench (HITL)"
            st.rerun()
    with b_col2:
        if st.button("Close Window", use_container_width=True):
            st.rerun()


def _render_take_action_page(action_cid: str) -> None:
    df_claims = load_claims_df()
    matched = df_claims[df_claims["claim_id"] == action_cid]

    if matched.empty:
        st.session_state.wb_action_claim_id = None
        st.session_state.agent_active_tab = "⚖️ Analyst Discrepancy Workbench (HITL)"
        st.rerun()

    claim_row = matched.iloc[0]
    lines_df = load_line_items_df(action_cid)
    just_data = load_justification(action_cid)
    display_explanation = get_consistent_explanation(claim_row, just_data)
    sup_replies_df = load_supplier_responses(action_cid)

    nav_col1, _ = st.columns([1.6, 4])
    with nav_col1:
        if st.button("← Back to Analyst Discrepancy Workbench", use_container_width=True):
            st.session_state.wb_action_claim_id = None
            st.session_state.agent_active_tab = "⚖️ Analyst Discrepancy Workbench (HITL)"
            st.rerun()

    st.header(
        f"⚡ Claim Resolution & Approval — `{action_cid}` | Invoice `{claim_row['invoice_number']}`"
    )
    st.caption(
        f"Supplier: **{claim_row['supplier_name']}** (`{claim_row['supplier_id']}`) | "
        f"PO Reference: `{claim_row['po_number']}` | Current Status: `{claim_row['status']}`"
    )

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Claimed Amount", f"${float(claim_row['total_claimed_amount']):,.2f}")
    m2.metric("ERP Approved Amount", f"${float(claim_row['total_approved_amount']):,.2f}")
    variance = float(claim_row["total_claimed_amount"]) - float(claim_row["total_approved_amount"])
    m3.metric("Net Deduction / Variance", f"${variance:,.2f}")
    m4.metric("Incoterms", claim_row["incoterms"])

    st.divider()
    left_col, right_col = st.columns([1, 1.2])

    with left_col:
        st.subheader("3-Way Match Summary")
        match_cols = [
            "sku",
            "claimed_qty",
            "erp_po_qty",
            "erp_grn_qty",
            "claimed_unit_price",
            "erp_unit_price",
            "variance_amount",
            "discrepancy_code",
        ]
        st.dataframe(lines_df[match_cols], use_container_width=True, hide_index=True)

        with st.expander("Retrieved Contract Clause", expanded=True):
            st.info(just_data.get("rag_contract_clause", "N/A"))

        with st.expander("Raw ERP Error Logs"):
            st.code(just_data.get("erp_raw_codes", "N/A"), language="text")

        st.subheader("💬 Claim Audit Thread (Supplier ↔ AR)")
        agent_thread_box = st.container(height=210, border=True)
        with agent_thread_box:
            if sup_replies_df.empty:
                st.caption("No supplier messages or counter-proof posted yet.")
            else:
                for _, entry in sup_replies_df.iterrows():
                    role_label = entry.get("sender_role") or "Supplier"
                    sender_label = entry.get("sender_name") or claim_row["supplier_name"]
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

        with st.form(key=f"agent_thread_reply_form_{action_cid}"):
            analyst_msg = st.text_input(
                "Reply to Supplier on Audit Thread (without closing claim):",
                placeholder="e.g., Please upload the carrier-signed BOL showing dock receipt...",
            )
            send_reply = st.form_submit_button("💬 Send Reply to Supplier", use_container_width=True)
            if send_reply and analyst_msg.strip():
                post_audit_thread_entry(
                    claim_id=action_cid,
                    supplier_id=claim_row["supplier_id"],
                    sender_role="Claim Processing Agent",
                    sender_name=f"{st.session_state.user_name} ({st.session_state.user_id})",
                    comment=analyst_msg,
                    mark_disputed=False,
                )
                st.success("Reply posted to the Supplier Audit Thread.")
                st.rerun()

    with right_col:
        st.subheader("Supplier Natural Language Justification")
        st.caption(
            "Review or customize the supplier-facing explanation below, then approve, reject, or go back without action."
        )

        edited_text = st.text_area(
            "Supplier-Ready Explanation:",
            value=display_explanation,
            height=310,
            key=f"action_page_textarea_{action_cid}_{claim_row['status']}",
        )

        btn_c1, btn_c2, btn_c3 = st.columns([1.4, 1.2, 1.1])
        with btn_c1:
            if st.button(
                "✅ Approve with Adjustment & Publish",
                type="primary",
                use_container_width=True,
            ):
                approve_claim_with_adjustment(
                    action_cid, edited_text, st.session_state.user_id
                )
                st.session_state.wb_flash_message = (
                    f"✅ Claim `{action_cid}` (Invoice `{claim_row['invoice_number']}`) has been approved "
                    "with adjustment, published to the Supplier Portal, and cleared from the open queue."
                )
                st.session_state.wb_action_claim_id = None
                st.session_state.agent_active_tab = "⚖️ Analyst Discrepancy Workbench (HITL)"
                st.rerun()

        with btn_c2:
            if st.button("🚫 Reject Entire Claim", use_container_width=True):
                reject_claim_in_full(
                    claim_id=action_cid,
                    claim_row=claim_row,
                    just_data=just_data,
                    edited_text=edited_text,
                    display_explanation=display_explanation,
                    agent_id=st.session_state.user_id,
                )
                st.session_state.wb_flash_message = (
                    f"🚫 Claim `{action_cid}` (Invoice `{claim_row['invoice_number']}`) has been REJECTED IN FULL, "
                    "published to the Supplier Portal, and cleared from the open queue."
                )
                st.session_state.wb_action_claim_id = None
                st.session_state.agent_active_tab = "⚖️ Analyst Discrepancy Workbench (HITL)"
                st.rerun()

        with btn_c3:
            if st.button("↩️ Back (No Action)", use_container_width=True):
                st.session_state.wb_action_claim_id = None
                st.session_state.agent_active_tab = "⚖️ Analyst Discrepancy Workbench (HITL)"
                st.rerun()


def _render_dashboard_tab() -> None:
    st.header("Accounts Receivable Claims — Operational Visibility")
    df_claims = load_claims_df()
    df_lines = load_line_items_df()

    if df_claims.empty:
        st.warning(
            "No claims found in database. Upload an invoice in Screen 3 or reset demo data in the sidebar."
        )
        return

    total_claims = len(df_claims)
    auto_approved = len(df_claims[df_claims["status"] == "AUTO_APPROVED"])
    pending_review = len(
        df_claims[
            df_claims["status"].isin(["DISCREPANCY_REVIEW", "DISPUTED_BY_SUPPLIER"])
        ]
    )
    stp_rate = (auto_approved / total_claims) * 100 if total_claims else 0.0
    disputed_value = (
        df_claims["total_claimed_amount"] - df_claims["total_approved_amount"]
    ).sum()

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Claims Ingested", total_claims)
    k2.metric("Straight-Through Processing (STP)", f"{stp_rate:.1f}%")

    with k3:
        st.metric("Open / Disputed Claims", pending_review)
        if st.button(
            f"⚖️ View Discrepancy Queue ({pending_review}) →",
            key="kpi_open_discrepancies_btn",
            type="primary" if pending_review > 0 else "secondary",
            use_container_width=True,
        ):
            st.session_state.wb_last_supplier = "ALL"
            st.session_state.wb_search_executed = True
            st.session_state.wb_action_claim_id = None
            st.session_state.agent_active_tab = "⚖️ Analyst Discrepancy Workbench (HITL)"
            st.rerun()

    k4.metric("Total Discrepancy Value Identified", f"${disputed_value:,.2f}")

    st.divider()
    col_c1, col_c2 = st.columns(2)

    with col_c1:
        st.subheader("Claims by Processing Status")
        status_counts = df_claims["status"].value_counts().reset_index()
        status_counts.columns = ["Status", "Count"]
        fig_status = px.pie(
            status_counts,
            names="Status",
            values="Count",
            hole=0.45,
            color_discrete_sequence=px.colors.qualitative.Set2,
        )
        st.plotly_chart(fig_status, use_container_width=True)

    with col_c2:
        st.subheader("Discrepancy Root Causes (Line Items)")
        disc_only = df_lines[df_lines["discrepancy_code"] != "MATCH_OK"]
        if not disc_only.empty:
            rc_counts = disc_only["discrepancy_code"].value_counts().reset_index()
            rc_counts.columns = ["Root Cause Code", "Occurrences"]
            fig_rc = px.bar(
                rc_counts,
                x="Root Cause Code",
                y="Occurrences",
                color="Root Cause Code",
                color_discrete_sequence=px.colors.qualitative.Pastel,
            )
            st.plotly_chart(fig_rc, use_container_width=True)
        else:
            st.info("No active discrepancies recorded yet.")

    st.subheader("All Claims Ledger")
    ledger_cols = [
        "claim_id",
        "supplier_id",
        "supplier_name",
        "invoice_number",
        "po_number",
        "file_format",
        "total_claimed_amount",
        "total_approved_amount",
        "status",
        "created_at",
    ]
    st.dataframe(df_claims[ledger_cols], use_container_width=True, hide_index=True)


def _render_workbench_tab() -> None:
    st.header("Analyst Discrepancy Workbench & Supplier Communication")

    if st.session_state.wb_flash_message:
        st.success(st.session_state.wb_flash_message)
        st.session_state.wb_flash_message = None

    df_claims = load_claims_df()
    suppliers_map = load_suppliers_map()

    if df_claims.empty:
        st.info("No claims available.")
        return

    sc1, sc2, sc3 = st.columns([2, 2, 1])
    supplier_dropdown_options = ["ALL — All Suppliers"] + [
        f"{sid} — {sname}" for sid, sname in suppliers_map.items()
    ]
    with sc1:
        selected_sup_option = st.selectbox(
            "Select Supplier:",
            options=supplier_dropdown_options,
            index=0,
            key="wb_sup_dropdown",
        )
    current_sup_code = selected_sup_option.split(" — ")[0]

    if current_sup_code != st.session_state.wb_last_supplier:
        st.session_state.wb_last_supplier = current_sup_code
        st.session_state.wb_search_executed = False

    with sc2:
        keyword_input = st.text_input(
            "Or Key In Supplier ID / Name:",
            placeholder="e.g., SUP-101 or Apex",
            key="wb_kw_input",
        )
    with sc3:
        st.write("")
        st.write("")
        if st.button("🔍 Search", type="primary", use_container_width=True):
            st.session_state.wb_search_executed = True

    st.divider()

    if not st.session_state.wb_search_executed:
        st.info(
            f"Supplier filter changed to **{selected_sup_option}**. Click **🔍 Search** to load open discrepancy records."
        )
        return

    open_discrepancy_statuses = ["DISCREPANCY_REVIEW", "DISPUTED_BY_SUPPLIER"]
    discrepant_df = df_claims[df_claims["status"].isin(open_discrepancy_statuses)].copy()

    if current_sup_code != "ALL":
        discrepant_df = discrepant_df[discrepant_df["supplier_id"] == current_sup_code]

    if keyword_input.strip():
        kw = keyword_input.strip().lower()
        discrepant_df = discrepant_df[
            discrepant_df["supplier_id"].str.lower().str.contains(kw, na=False)
            | discrepant_df["supplier_name"].str.lower().str.contains(kw, na=False)
        ]

    if discrepant_df.empty:
        st.success("No open discrepancy records pending action for the selected supplier.")
        return

    st.subheader(f"Open Discrepancy Records ({len(discrepant_df)})")

    h_cols = st.columns([1.4, 1.7, 1.3, 1.1, 1.1, 1.1, 1.6, 1.1, 1.2])
    headers = [
        "Claim ID",
        "Supplier",
        "Invoice #",
        "Claimed",
        "Approved",
        "Variance",
        "Status",
        "Details",
        "Action",
    ]
    for col_box, title in zip(h_cols, headers):
        col_box.markdown(f"**{title}**")

    st.markdown("---")

    for _, row in discrepant_df.iterrows():
        cid = row["claim_id"]
        var_amt = float(row["total_claimed_amount"]) - float(row["total_approved_amount"])
        r_cols = st.columns([1.4, 1.7, 1.3, 1.1, 1.1, 1.1, 1.6, 1.1, 1.2])

        r_cols[0].write(f"`{cid}`")
        r_cols[1].write(f"{row['supplier_name']} (`{row['supplier_id']}`)")
        r_cols[2].write(row["invoice_number"])
        r_cols[3].write(f"${float(row['total_claimed_amount']):,.2f}")
        r_cols[4].write(f"${float(row['total_approved_amount']):,.2f}")
        r_cols[5].write(f"${var_amt:,.2f}")
        r_cols[6].write(f"`{row['status']}`")

        if r_cols[7].button("👁️ View", key=f"btn_view_{cid}", use_container_width=True):
            show_discrepancy_modal(cid)

        if r_cols[8].button(
            "⚡ Take Action",
            key=f"btn_act_{cid}",
            type="primary",
            use_container_width=True,
        ):
            st.session_state.wb_action_claim_id = cid
            st.rerun()


def _render_upload_tab(get_workflow_fn) -> None:
    st.header("Invoice & Claim Upload")
    st.write(
        "Step 1: Upload an incoming supplier invoice or claim file (**PDF, PNG, JPEG, XML, or EDI**) "
        "and fetch its details for verification. Step 2: Process the verified invoice to run 3-way ERP reconciliation."
    )

    uploaded_file = st.file_uploader(
        "Select Invoice / Claim Document",
        type=["pdf", "png", "jpg", "jpeg", "xml", "edi", "x12", "txt"],
        key="claim_file_uploader",
    )

    if uploaded_file is None:
        st.session_state.pop("staged_invoice_preview", None)
    else:
        file_bytes = uploaded_file.getvalue()
        file_signature = f"{uploaded_file.name}_{len(file_bytes)}"

        staged = st.session_state.get("staged_invoice_preview")
        if staged and staged.get("signature") != file_signature:
            st.session_state.pop("staged_invoice_preview", None)
            staged = None

        if staged is None:
            if st.button("🔍 Fetch Details from File", type="primary"):
                with st.spinner("Extracting invoice header and line items from document..."):
                    extracted_claim, raw_text = ingest_document(uploaded_file.name, file_bytes)
                st.session_state["staged_invoice_preview"] = {
                    "signature": file_signature,
                    "filename": uploaded_file.name,
                    "file_bytes": file_bytes,
                    "canonical_claim": extracted_claim,
                    "raw_text": raw_text,
                }
                st.session_state.pop("last_upload_result", None)
                st.rerun()

        staged = st.session_state.get("staged_invoice_preview")
        if staged is not None:
            claim_preview = staged["canonical_claim"]
            suppliers_map = load_suppliers_map()
            sup_display_name = suppliers_map.get(
                claim_preview.supplier_id, "Unregistered Supplier"
            )
            total_preview_amt = sum(
                item.claimed_qty * item.claimed_unit_price for item in claim_preview.line_items
            )

            st.divider()
            st.subheader("📋 Extracted Invoice Details (Ready for Processing)")

            f1, f2, f3, f4, f5 = st.columns(5)
            f1.metric("Supplier ID", f"{claim_preview.supplier_id}")
            f2.metric("Invoice Number", claim_preview.invoice_number)
            f3.metric("PO Reference", claim_preview.po_number)
            f4.metric("Detected Format", claim_preview.file_format)
            f5.metric("Total Claimed", f"${total_preview_amt:,.2f}")

            st.caption(f"Matched Vendor Name: **{sup_display_name}**")

            preview_rows = [
                {
                    "Item SKU": item.sku,
                    "Claimed Qty": item.claimed_qty,
                    "Claimed Unit Price ($)": item.claimed_unit_price,
                    "Line Total ($)": round(item.claimed_qty * item.claimed_unit_price, 2),
                }
                for item in claim_preview.line_items
            ]
            st.dataframe(pd.DataFrame(preview_rows), use_container_width=True, hide_index=True)

            with st.expander("View Raw Extracted Document / OCR Text"):
                st.code(staged["raw_text"], language="text")

            act_c1, act_c2, _ = st.columns([1.4, 1.1, 2])
            with act_c1:
                if st.button(
                    "⚡ Process Invoice & Run 3-Way Match",
                    type="primary",
                    use_container_width=True,
                ):
                    graph = get_workflow_fn()
                    with st.spinner("Running 3-way ERP reconciliation and contract validation..."):
                        final_state = graph.invoke(
                            {
                                "filename": staged["filename"],
                                "file_bytes": staged["file_bytes"],
                                "execution_trace": [],
                            }
                        )
                    st.session_state["last_upload_result"] = final_state
                    st.session_state.pop("staged_invoice_preview", None)
                    st.rerun()

            with act_c2:
                if st.button("✖ Discard Preview", use_container_width=True):
                    st.session_state.pop("staged_invoice_preview", None)
                    st.rerun()

    if "last_upload_result" in st.session_state and st.session_state["last_upload_result"]:
        final_state = st.session_state["last_upload_result"]
        st.divider()
        if final_state["status"] == "AUTO_APPROVED":
            st.success(
                f"**Valid & Auto-Approved** — Claim ID `{final_state['claim_id']}` matched cleanly "
                f"for **${final_state['total_approved']:,.2f}**. Screen 1 & Screen 2 are updated."
            )
        else:
            variance = final_state["total_claimed"] - final_state["total_approved"]
            st.warning(
                f"**Discrepancy Detected** — Claim ID `{final_state['claim_id']}` has a variance of "
                f"**${variance:,.2f}** (Claimed: ${final_state['total_claimed']:,.2f} | "
                f"Approved: ${final_state['total_approved']:,.2f}). Screen 1 & Screen 2 are updated."
            )

        col_res1, col_res2 = st.columns([1, 1.2])
        with col_res1:
            st.subheader("Validation Summary")
            for step in final_state["execution_trace"]:
                st.write(step)

        with col_res2:
            st.subheader("Generated Supplier Justification")
            st.text_area(
                "Explanation Preview",
                value=final_state["natural_language_justification"],
                height=220,
                disabled=True,
            )


def render_agent_portal(get_workflow_fn) -> None:
    if st.session_state.wb_action_claim_id:
        _render_take_action_page(st.session_state.wb_action_claim_id)
        return

    agent_tabs = [
        "📊 Executive & Operations Dashboard",
        "⚖️ Analyst Discrepancy Workbench (HITL)",
        "📤 Invoice & Claim Upload",
    ]
    selected_tab = st.radio(
        "Workspace Navigation",
        options=agent_tabs,
        index=agent_tabs.index(st.session_state.agent_active_tab),
        horizontal=True,
        label_visibility="collapsed",
    )
    if selected_tab != st.session_state.agent_active_tab:
        st.session_state.agent_active_tab = selected_tab
        st.rerun()

    st.divider()

    if st.session_state.agent_active_tab == "📊 Executive & Operations Dashboard":
        _render_dashboard_tab()
    elif st.session_state.agent_active_tab == "⚖️ Analyst Discrepancy Workbench (HITL)":
        _render_workbench_tab()
    elif st.session_state.agent_active_tab == "📤 Invoice & Claim Upload":
        _render_upload_tab(get_workflow_fn)
