# AR Claims AI & Discrepancy Resolution Portal

Modular multi-agent Accounts Receivable (AR) Claims & Discrepancy Resolution application built with Streamlit, LangGraph, ChromaDB, and SQLite.

## Project Structure
- `app.py`: Entry point, session initialization, sidebar controller, and RBAC role router.
- `ui/login.py`: Two-column enterprise login screen with persona context cards.
- `ui/supplier_portal.py`: Supplier Discrepancy & Settlement Portal, Tier-1 AI Dispute Assistant, and Tier-2 Claim Audit Thread.
- `ui/agent_portal.py`: Executive Dashboard (with clickable KPI navigation), Analyst Workbench (with supplier search, `@st.dialog` modal, and full-screen Take Action page), and Two-Step Invoice Upload.
- `db/database.py`: SQLite schema initialization (WAL mode) with auto-migration.
- `db/repository.py`: Centralized SQL queries, audit thread persistence, and self-healing explanation sync.
- `agents/ingestion.py`: XML, EDI 810, PDF, and RapidOCR / OpenAI Vision document extraction.
- `agents/workflow.py`: LangGraph 3-way reconciliation, ChromaDB policy RAG, and justification pipeline.
- `agents/assistant.py`: Context-aware Tier-1 Supplier AI Dispute Assistant.
- `mcp_servers/erp_mcp_server.py`: FastMCP ERP tool definitions.
- `seed_data.py`: Seeds SQLite, ChromaDB, and sample XML/EDI/PNG claim files.

## Quick Start
1. Create and activate your virtual environment, then install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Copy `.env.example` to `.env` (keep `USE_MOCK_LLM=true` for offline demo mode, or set `USE_MOCK_LLM=false` with your `OPENAI_API_KEY`).
3. Seed the demo databases and sample files:
   ```bash
   python seed_data.py
   ```
4. Launch the portal:
   ```bash
   streamlit run app.py
   ```
