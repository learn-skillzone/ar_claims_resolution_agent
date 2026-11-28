import os
import streamlit as st
from dotenv import load_dotenv

from db.database import DB_PATH, init_db
from seed_data import seed_sqlite, seed_chromadb, create_sample_files
from agents.workflow import build_claims_graph, _get_contracts_collection
from ui.login import render_login_screen
from ui.supplier_portal import render_supplier_portal
from ui.agent_portal import render_agent_portal

load_dotenv()

st.set_page_config(
    page_title="AR Claims AI & Discrepancy Resolution Portal",
    page_icon="📊",
    layout="wide",
)

init_db()
if not os.path.exists(DB_PATH):
    seed_sqlite()
    seed_chromadb()
    create_sample_files()


@st.cache_resource
def get_compiled_workflow():
    _get_contracts_collection()
    return build_claims_graph()


def init_session_state() -> None:
    defaults = {
        "authenticated": False,
        "user_role": None,
        "user_id": None,
        "user_name": None,
        "agent_active_tab": "📊 Executive & Operations Dashboard",
        "wb_last_supplier": "ALL",
        "wb_search_executed": True,
        "wb_action_claim_id": None,
        "wb_flash_message": None,
        "supplier_ai_chats": {},
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


def logout() -> None:
    st.session_state.authenticated = False
    st.session_state.user_role = None
    st.session_state.user_id = None
    st.session_state.user_name = None
    st.session_state.agent_active_tab = "📊 Executive & Operations Dashboard"
    st.session_state.wb_action_claim_id = None
    st.session_state.wb_flash_message = None
    st.session_state.supplier_ai_chats = {}
    st.session_state.pop("staged_invoice_preview", None)
    st.session_state.pop("last_upload_result", None)
    st.rerun()


init_session_state()

if not st.session_state.authenticated:
    render_login_screen()
    st.stop()

with st.sidebar:
    st.title("AR Claims AI Studio")
    st.caption("Automated 3-Way Match & Dispute Resolution")
    st.divider()

    st.markdown(f"**Logged in as:** {st.session_state.user_name}")
    st.markdown(f"**Role:** `{st.session_state.user_role}`")
    st.markdown(f"**Account ID:** `{st.session_state.user_id}`")

    if st.button("🚪 Logout / Switch Role", use_container_width=True):
        logout()

    if st.session_state.user_role == "Claim Processing Agent":
        st.divider()
        mode = (
            "Offline Demo Mode (Zero API Cost)"
            if os.getenv("USE_MOCK_LLM", "true").lower() == "true"
            else f"Live AI Engine ({os.getenv('LLM_MODEL', 'gpt-4o-mini')})"
        )
        st.info(f"**Engine Mode:** {mode}")
        if st.button("Reset & Re-Seed Demo Database", use_container_width=True):
            seed_sqlite()
            seed_chromadb()
            create_sample_files()
            st.session_state.wb_action_claim_id = None
            st.session_state.wb_flash_message = None
            st.session_state.supplier_ai_chats = {}
            st.session_state.pop("staged_invoice_preview", None)
            st.session_state.pop("last_upload_result", None)
            st.success("Demo database reset!")
            st.rerun()

if st.session_state.user_role == "Supplier":
    render_supplier_portal()
elif st.session_state.user_role == "Claim Processing Agent":
    render_agent_portal(get_compiled_workflow)
