import streamlit as st
from db.repository import load_suppliers_map

LOGIN_CSS = """
<style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .block-container {
        padding-top: 2.5rem;
        padding-bottom: 2rem;
        max-width: 1140px;
    }
    .hero-card {
        background: linear-gradient(145deg, #0f172a 0%, #1e293b 55%, #0f4c81 100%);
        color: #f8fafc;
        padding: 2.6rem 2.4rem;
        border-radius: 18px;
        box-shadow: 0 20px 35px -10px rgba(15, 23, 42, 0.25);
        height: 100%;
        border: 1px solid rgba(255, 255, 255, 0.08);
    }
    .hero-badge {
        display: inline-block;
        background: rgba(56, 189, 248, 0.16);
        color: #7dd3fc;
        font-size: 0.78rem;
        font-weight: 600;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        padding: 0.35rem 0.8rem;
        border-radius: 999px;
        border: 1px solid rgba(125, 211, 252, 0.3);
        margin-bottom: 1.2rem;
    }
    .hero-title {
        font-size: 2.05rem;
        font-weight: 700;
        line-height: 1.2;
        margin-bottom: 0.85rem;
        color: #ffffff;
    }
    .hero-subtitle {
        font-size: 0.98rem;
        line-height: 1.6;
        color: #cbd5e1;
        margin-bottom: 1.8rem;
    }
    .feature-item {
        display: flex;
        align-items: flex-start;
        gap: 0.85rem;
        margin-bottom: 1.15rem;
        background: rgba(255, 255, 255, 0.05);
        padding: 0.85rem 1rem;
        border-radius: 12px;
        border: 1px solid rgba(255, 255, 255, 0.06);
    }
    .feature-icon {
        font-size: 1.25rem;
        line-height: 1.2;
    }
    .feature-title {
        font-weight: 600;
        font-size: 0.94rem;
        color: #f1f5f9;
        margin-bottom: 0.15rem;
    }
    .feature-desc {
        font-size: 0.83rem;
        color: #94a3b8;
        line-height: 1.4;
    }
    .hero-footer {
        margin-top: 1.6rem;
        padding-top: 1rem;
        border-top: 1px solid rgba(255, 255, 255, 0.1);
        font-size: 0.8rem;
        color: #94a3b8;
        display: flex;
        justify-content: space-between;
    }
    .login-header {
        margin-bottom: 0.4rem;
    }
    .login-header h2 {
        margin: 0;
        font-size: 1.65rem;
        font-weight: 700;
        color: #0f172a;
    }
    .login-sub {
        color: #64748b;
        font-size: 0.92rem;
        margin-bottom: 1.2rem;
    }
    .role-context-box {
        background-color: #f1f5f9;
        border-left: 4px solid #0284c7;
        padding: 0.75rem 1rem;
        border-radius: 0 8px 8px 0;
        margin: 0.6rem 0 1.1rem 0;
        font-size: 0.86rem;
        color: #334155;
    }
</style>
"""


def render_login_screen() -> None:
    st.markdown(LOGIN_CSS, unsafe_allow_html=True)

    left_hero, _, right_login = st.columns([1.2, 0.08, 1])

    with left_hero:
        st.markdown(
            """
            <div class="hero-card">
                <div class="hero-badge">Enterprise AR Automation</div>
                <div class="hero-title">AR Claims & Discrepancy Resolution Studio</div>
                <div class="hero-subtitle">
                    Accelerate invoice settlement, automate 3-way ERP reconciliation, and resolve supplier deductions with transparent, policy-backed explanations.
                </div>
                <div class="feature-item">
                    <div class="feature-icon">⚡</div>
                    <div>
                        <div class="feature-title">Automated 3-Way ERP Matching</div>
                        <div class="feature-desc">Instant cross-verification across Supplier Invoices, Purchase Orders, and Warehouse Goods Receipts.</div>
                    </div>
                </div>
                <div class="feature-item">
                    <div class="feature-icon">⚖️</div>
                    <div>
                        <div class="feature-title">Contract-Grounded Discrepancy Resolution</div>
                        <div class="feature-desc">Cites governing MSA clauses and generates plain-language adjustment notices for rapid sign-off.</div>
                    </div>
                </div>
                <div class="feature-item">
                    <div class="feature-icon">🤖</div>
                    <div>
                        <div class="feature-title">AI Dispute Assistant & Audit Thread</div>
                        <div class="feature-desc">Instant Tier-1 invoice Q&A paired with a claim-level evidentiary log for counter-proof review.</div>
                    </div>
                </div>
                <div class="hero-footer">
                    <span>🔒 Role-Based Access Control</span>
                    <span>•</span>
                    <span>Audit-Logged Decisions</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with right_login:
        with st.container(border=True):
            st.markdown(
                """
                <div class="login-header">
                    <h2>Welcome Back</h2>
                </div>
                <div class="login-sub">Choose your workspace persona and sign in to continue.</div>
                """,
                unsafe_allow_html=True,
            )

            selected_role = st.radio(
                "Sign in as:",
                ["Claim Processing Agent", "Supplier"],
                horizontal=True,
            )

            if selected_role == "Claim Processing Agent":
                st.markdown(
                    '<div class="role-context-box"><strong>Internal AR Operations:</strong> Access the executive KPI dashboard, upload incoming invoices, and review or approve discrepancy adjustments.</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    '<div class="role-context-box"><strong>Vendor Self-Service Portal:</strong> View discrepant invoices, ask our AI Dispute Assistant, and submit supporting proof.</div>',
                    unsafe_allow_html=True,
                )

            with st.form("rbac_login_form", border=False):
                if selected_role == "Supplier":
                    suppliers_map = load_suppliers_map()
                    supplier_choices = [
                        f"{sid} — {sname}" for sid, sname in suppliers_map.items()
                    ]
                    chosen_supplier = st.selectbox("Supplier Organization", supplier_choices)
                    passcode = st.text_input(
                        "Portal Passcode",
                        type="password",
                        value="supplier123",
                        placeholder="Enter your supplier passcode",
                    )
                    st.caption("Demo credentials pre-filled (`supplier123`)")
                else:
                    agent_id = st.text_input(
                        "Agent Employee ID",
                        value="AR-AGENT-01",
                        placeholder="e.g., AR-AGENT-01",
                    )
                    passcode = st.text_input(
                        "Workspace Passcode",
                        type="password",
                        value="agent123",
                        placeholder="Enter your agent passcode",
                    )
                    st.caption("Demo credentials pre-filled (`agent123`)")

                st.write("")
                submitted = st.form_submit_button(
                    f"Sign In as {selected_role} →",
                    type="primary",
                    use_container_width=True,
                )

                if submitted:
                    if not passcode.strip():
                        st.error("Please enter a passcode to sign in.")
                    else:
                        st.session_state.authenticated = True
                        st.session_state.user_role = selected_role
                        if selected_role == "Supplier":
                            sid, sname = chosen_supplier.split(" — ", 1)
                            st.session_state.user_id = sid
                            st.session_state.user_name = sname
                        else:
                            st.session_state.user_id = agent_id.strip() or "AR-AGENT-01"
                            st.session_state.user_name = "AR Claims Specialist"
                        st.rerun()
