import os
import time
import streamlit as st
from dotenv import load_dotenv

from db.database import DB_PATH
from seed_data import seed_sqlite, seed_chromadb, create_sample_files
from agents.workflow import build_claims_graph

load_dotenv()

st.set_page_config(
    page_title="Orchestrator Decision & Agent Flow Visualizer",
    page_icon="🧠",
    layout="wide",
)

# Ensure database and sample files exist
if not os.path.exists(DB_PATH):
    seed_sqlite()
    seed_chromadb()
    create_sample_files()


def render_highlighted_graphviz(visited_nodes: list[str], current_node: str | None = None, branch_taken: str | None = None) -> str:
    """
    Generates a Graphviz DOT diagram highlighting the active node,
    completed path, and the exact conditional branch chosen by the Orchestrator.
    """
    nodes_meta = {
        "__start__": ("START\n(Incoming Claim)", "oval"),
        "ingest": ("1. Ingestion Agent\n(XML / EDI / PDF / Vision)", "box"),
        "reconcile": ("2. ERP Reconciliation Agent\n(MCP 3-Way Match)", "box"),
        "router": ("Orchestrator Router\n(has_discrepancy?)", "diamond"),
        "policy_rag": ("3A. Policy RAG Agent\n(ChromaDB Contracts)", "box"),
        "justify": ("4. Justification Agent\n(NLG Explanation)", "box"),
        "auto_approve": ("3B. Auto-Approval Node\n(Straight-Through STP)", "box"),
        "persist": ("5. Persistence Agent\n(SQLite Operational Store)", "box"),
        "__end__": ("END\n(Dashboard & HITL Ready)", "oval"),
    }

    dot_lines = [
        "digraph AgentOrchestrator {",
        '  rankdir=TB;',
        '  bgcolor="transparent";',
        '  node [fontname="Helvetica", fontsize=11, style="rounded,filled", margin="0.18,0.12"];',
        '  edge [fontname="Helvetica", fontsize=10, color="#64748B"];',
    ]

    for node_id, (label, shape) in nodes_meta.items():
        if node_id == current_node:
            fill = "#FDE047"   # Bright Yellow = Currently Executing
            border = "#CA8A04"
            penwidth = "2.5"
        elif node_id in visited_nodes:
            fill = "#BBF7D0"   # Soft Green = Completed Step
            border = "#16A34A"
            penwidth = "2.0"
        else:
            fill = "#F1F5F9"   # Slate Gray = Not Yet Visited / Untaken Branch
            border = "#94A3B8"
            penwidth = "1.2"

        safe_label = label.replace("\n", "\\n")
        dot_lines.append(
            f'  "{node_id}" [label="{safe_label}", shape={shape}, fillcolor="{fill}", color="{border}", penwidth={penwidth}];'
        )

    # Edges with dynamic highlighting on the chosen decision path
    edges = [
        ("__start__", "ingest", " raw file", True),
        ("ingest", "reconcile", " CanonicalClaim JSON", "reconcile" in visited_nodes),
        ("reconcile", "router", " 3-way match delta", "router" in visited_nodes),
        ("router", "policy_rag", " TRUE (Variance > $0)", branch_taken == "policy_rag"),
        ("policy_rag", "justify", " MSA clause", "justify" in visited_nodes),
        ("justify", "persist", " DISCREPANCY_REVIEW", "justify" in visited_nodes and "persist" in visited_nodes),
        ("router", "auto_approve", " FALSE ($0 Variance)", branch_taken == "auto_approve"),
        ("auto_approve", "persist", " AUTO_APPROVED", "auto_approve" in visited_nodes and "persist" in visited_nodes),
        ("persist", "__end__", " committed", "__end__" in visited_nodes),
    ]

    for src, dst, lbl, active in edges:
        if active:
            dot_lines.append(f'  "{src}" -> "{dst}" [label="{lbl}", color="#16A34A", penwidth=2.5, fontcolor="#15803D"];')
        else:
            dot_lines.append(f'  "{src}" -> "{dst}" [label="{lbl}", style="dashed", color="#CBD5E1", fontcolor="#94A3B8"];')

    dot_lines.append("}")
    return "\n".join(dot_lines)


st.title("🧠 Multi-Agent Orchestrator — Live Decision Visualizer")
st.markdown(
    "Watch how the **LangGraph Supervisor/Orchestrator** inspects intermediate state, "
    "invokes specialized sub-agents (MCP, ChromaDB RAG, NLG), and dynamically routes claims."
)

col_ctrl, col_viz = st.columns([1, 1.4])

with col_ctrl:
    st.subheader("1. Select Test Scenario")
    scenarios = {
        "Scenario A: Damaged Goods Shortage (XML -> Discrepancy Path)": "sample_data/claim_apex_damaged_qty.xml",
        "Scenario B: Clean 3-Way Match (EDI -> Auto-Approve STP Path)": "sample_data/claim_globalfresh_clean.edi",
        "Scenario C: Unauthorized Price Surcharge (OCR -> Discrepancy Path)": "sample_data/claim_metropack_ocr_scan.txt",
    }
    choice = st.radio("Choose claim payload:", list(scenarios.keys()))
    step_delay = st.slider("Animation Step Delay (seconds)", min_value=0.0, max_value=2.0, value=0.7, step=0.1)

    sample_path = scenarios[choice]
    with open(sample_path, "rb") as f:
        sample_bytes = f.read()

    with st.expander("Inspect Raw Input Payload"):
        st.code(sample_bytes.decode("utf-8", errors="ignore"))

    run_btn = st.button("▶️ Step-by-Step Orchestrator Execution", type="primary", use_container_width=True)

    st.divider()
    st.subheader("2. Raw LangGraph Mermaid Export")
    graph = build_claims_graph()
    with st.expander("View Native LangGraph Mermaid Definition"):
        st.code(graph.get_graph().draw_mermaid(), language="mermaid")

with col_viz:
    st.subheader("Live Execution Topology & Decision Path")
    chart_placeholder = st.empty()
    decision_banner = st.empty()
    logs_container = st.container()

    # Initial idle state diagram
    chart_placeholder.graphviz_chart(render_highlighted_graphviz(visited_nodes=["__start__"]))

    if run_btn:
        visited = ["__start__"]
        branch_taken = None
        step_num = 0

        initial_input = {
            "filename": os.path.basename(sample_path),
            "file_bytes": sample_bytes,
            "execution_trace": [],
        }

        # Stream node-by-node execution from LangGraph
        for event in graph.stream(initial_input, stream_mode="updates"):
            for node_name, state_delta in event.items():
                step_num += 1
                visited.append(node_name)

                # Highlight router decision explicitly right after reconciliation
                if node_name == "reconcile":
                    visited.append("router")
                    has_disc = state_delta.get("has_discrepancy", False)
                    branch_taken = "policy_rag" if has_disc else "auto_approve"

                    if has_disc:
                        decision_banner.warning(
                            f"**Orchestrator Decision Gate:** `has_discrepancy == True` "
                            f"(Claimed ${state_delta['total_claimed']:,.2f} vs. Approved ${state_delta['total_approved']:,.2f}). "
                            f"Routing to **Policy RAG Agent (ChromaDB)**."
                        )
                    else:
                        decision_banner.success(
                            f"**Orchestrator Decision Gate:** `has_discrepancy == False` "
                            f"(${state_delta['total_approved']:,.2f} exact 3-way match). "
                            f"Bypassing RAG and routing to **Auto-Approval (STP)**."
                        )

                chart_placeholder.graphviz_chart(
                    render_highlighted_graphviz(
                        visited_nodes=visited,
                        current_node=node_name,
                        branch_taken=branch_taken,
                    )
                )

                with logs_container:
                    with st.expander(f"Step {step_num}: Node `{node_name}` Output & State Mutation", expanded=True):
                        if "execution_trace" in state_delta and state_delta["execution_trace"]:
                            st.write(f"**Action:** {state_delta['execution_trace'][-1]}")
                        # Display clean summary of mutated keys
                        summary_dict = {
                            k: (str(v) if k not in ["reconciliation_results"] else [r.model_dump() for r in v])
                            for k, v in state_delta.items()
                            if k not in ["execution_trace", "file_bytes", "raw_text"]
                        }
                        st.json(summary_dict)

                if step_delay > 0:
                    time.sleep(step_delay)

        visited.append("__end__")
        chart_placeholder.graphviz_chart(
            render_highlighted_graphviz(
                visited_nodes=visited,
                current_node=None,
                branch_taken=branch_taken,
            )
        )
        st.balloons()