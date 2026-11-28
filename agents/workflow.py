import os
import json
import uuid
from datetime import datetime
from typing import TypedDict, List, Optional, Tuple
import chromadb
from chromadb.utils import embedding_functions
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI

from agents.schemas import CanonicalClaim, LineDiscrepancyResult
from agents.ingestion import ingest_document
from mcp_servers.erp_mcp_server import get_purchase_order, get_goods_receipt, get_supplier_profile
from db.database import get_connection

CHROMA_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "db", "chroma_store"))
_CHROMA_CACHE: dict[Tuple[str, str], object] = {}


def _is_live_openai_enabled() -> bool:
    use_mock = os.getenv("USE_MOCK_LLM", "true").strip().lower() == "true"
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    return (not use_mock) and bool(api_key)


def get_embedding_function():
    """Returns OpenAI embeddings when USE_MOCK_LLM=false, else built-in Chroma embeddings."""
    if _is_live_openai_enabled():
        model_name = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small").strip()
        return embedding_functions.OpenAIEmbeddingFunction(
            api_key=os.getenv("OPENAI_API_KEY").strip(),
            model_name=model_name,
        )
    return embedding_functions.DefaultEmbeddingFunction()


def _get_contracts_collection():
    """Singleton cache for ChromaDB collection keyed by active embedding mode."""
    mode_key = "openai" if _is_live_openai_enabled() else "builtin"
    model_key = (
        os.getenv("EMBEDDING_MODEL", "text-embedding-3-small").strip()
        if mode_key == "openai"
        else "default"
    )
    cache_key = (mode_key, model_key)

    if cache_key not in _CHROMA_CACHE:
        client = chromadb.PersistentClient(path=CHROMA_PATH)
        ef = get_embedding_function()
        _CHROMA_CACHE[cache_key] = client.get_or_create_collection(
            name="supplier_contracts", embedding_function=ef
        )
    return _CHROMA_CACHE[cache_key]


class ClaimGraphState(TypedDict):
    filename: str
    file_bytes: bytes
    raw_text: str
    claim_id: str
    canonical_claim: Optional[CanonicalClaim]
    supplier_profile: dict
    reconciliation_results: List[LineDiscrepancyResult]
    has_discrepancy: bool
    total_claimed: float
    total_approved: float
    rag_contract_clause: str
    natural_language_justification: str
    status: str
    execution_trace: List[str]


def node_ingest(state: ClaimGraphState) -> dict:
    claim, raw_text = ingest_document(state["filename"], state["file_bytes"])
    claim_id = f"CLM-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:4].upper()}"
    trace = state.get("execution_trace", []) + [
        f"[1. Ingestion Agent] Parsed {claim.file_format} file '{state['filename']}' -> Invoice {claim.invoice_number}, PO {claim.po_number} ({len(claim.line_items)} line items)."
    ]
    return {
        "claim_id": claim_id,
        "canonical_claim": claim,
        "raw_text": raw_text,
        "execution_trace": trace,
    }


def node_reconcile(state: ClaimGraphState) -> dict:
    claim = state["canonical_claim"]
    po_data = json.loads(get_purchase_order(claim.po_number))
    grn_data = json.loads(get_goods_receipt(claim.po_number))
    sup_data = json.loads(get_supplier_profile(claim.supplier_id))

    po_map = {item["sku"]: item for item in po_data.get("items", [])}
    grn_map = {rec["sku"]: rec for rec in grn_data.get("receipts", [])}
    supplier_profile = sup_data.get("supplier", {"incoterms": "Unknown", "supplier_name": claim.supplier_id})

    results: List[LineDiscrepancyResult] = []
    has_discrepancy = False
    total_claimed = 0.0
    total_approved = 0.0

    for line in claim.line_items:
        line_claimed = line.claimed_qty * line.claimed_unit_price
        total_claimed += line_claimed

        po_item = po_map.get(line.sku)
        grn_item = grn_map.get(line.sku)

        if not po_item:
            has_discrepancy = True
            results.append(
                LineDiscrepancyResult(
                    sku=line.sku,
                    claimed_qty=line.claimed_qty,
                    erp_po_qty=0,
                    erp_grn_qty=0,
                    claimed_unit_price=line.claimed_unit_price,
                    erp_unit_price=0.0,
                    approved_line_amount=0.0,
                    variance_amount=-line_claimed,
                    discrepancy_code="ERR_SKU_NOT_ON_PO",
                    erp_detail=f"SKU {line.sku} does not exist on Purchase Order {claim.po_number}.",
                )
            )
            continue

        po_qty = po_item["ordered_qty"]
        po_price = po_item["unit_price"]
        grn_good_qty = grn_item["received_good_qty"] if grn_item else po_qty
        damaged_qty = grn_item["damaged_qty"] if grn_item else 0
        grn_notes = grn_item["receiving_notes"] if grn_item else ""

        approved_qty = min(line.claimed_qty, grn_good_qty)
        approved_price = min(line.claimed_unit_price, po_price)
        approved_amt = round(approved_qty * approved_price, 2)
        variance = round(approved_amt - line_claimed, 2)
        total_approved += approved_amt

        codes = []
        details = []

        if line.claimed_qty > grn_good_qty:
            codes.append("ERR_GRN_QTY_SHORTAGE")
            details.append(
                f"Billed {line.claimed_qty} units, but warehouse GRN accepted {grn_good_qty} good units "
                f"({damaged_qty} damaged/rejected). Warehouse note: '{grn_notes}'"
            )

        if line.claimed_unit_price > po_price:
            codes.append("ERR_PRICE_VAR_EXCEEDED")
            details.append(
                f"Billed unit price ${line.claimed_unit_price:.2f} exceeds PO contracted price ${po_price:.2f}."
            )

        if codes:
            has_discrepancy = True
            code_str = " + ".join(codes)
            detail_str = " ".join(details)
        else:
            code_str = "MATCH_OK"
            detail_str = "3-way match succeeded (PO Qty, GRN Qty, and PO Unit Price aligned)."

        results.append(
            LineDiscrepancyResult(
                sku=line.sku,
                claimed_qty=line.claimed_qty,
                erp_po_qty=po_qty,
                erp_grn_qty=grn_good_qty,
                claimed_unit_price=line.claimed_unit_price,
                erp_unit_price=po_price,
                approved_line_amount=approved_amt,
                variance_amount=variance,
                discrepancy_code=code_str,
                erp_detail=detail_str,
            )
        )

    trace = state["execution_trace"] + [
        f"[2. ERP Reconciliation Agent (MCP)] Queried PO {claim.po_number} & GRN. "
        f"Claimed: ${total_claimed:,.2f} | Approved: ${total_approved:,.2f} | Discrepancy Found: {has_discrepancy}."
    ]

    return {
        "supplier_profile": supplier_profile,
        "reconciliation_results": results,
        "has_discrepancy": has_discrepancy,
        "total_claimed": round(total_claimed, 2),
        "total_approved": round(total_approved, 2),
        "execution_trace": trace,
    }


def node_policy_rag(state: ClaimGraphState) -> dict:
    claim = state["canonical_claim"]
    discrepant_lines = [r for r in state["reconciliation_results"] if r.discrepancy_code != "MATCH_OK"]
    query_text = " ".join([f"{r.discrepancy_code} {r.erp_detail}" for r in discrepant_lines])

    collection = _get_contracts_collection()

    results = collection.query(
        query_texts=[query_text],
        n_results=1,
        where={"supplier_id": claim.supplier_id},
    )

    docs = results.get("documents", [[]])[0]
    clause = docs[0] if docs else "Standard Corporate Terms: Settlement is strictly bound by verified GRN quantities and contracted PO unit prices."

    trace = state["execution_trace"] + [
        f"[3. Policy RAG Agent (ChromaDB)] Retrieved governing contract clause for {claim.supplier_id}."
    ]
    return {"rag_contract_clause": clause, "execution_trace": trace}


def node_generate_justification(state: ClaimGraphState) -> dict:
    claim = state["canonical_claim"]
    supplier_name = state["supplier_profile"].get("supplier_name", claim.supplier_id)
    discrepancies = [r for r in state["reconciliation_results"] if r.discrepancy_code != "MATCH_OK"]
    variance_total = round(state["total_claimed"] - state["total_approved"], 2)

    if _is_live_openai_enabled():
        llm = ChatOpenAI(model=os.getenv("LLM_MODEL", "gpt-4o-mini"), temperature=0.2)
        prompt = f"""You are a helpful Accounts Receivable Dispute Resolution Specialist.
Write a clear, polite, jargon-free explanation to the supplier explaining why their claim was partially adjusted.
Avoid raw ERP error codes. Cite the contract clause naturally.

Supplier: {supplier_name} ({claim.supplier_id})
Invoice Number: {claim.invoice_number}
PO Number: {claim.po_number}
Total Claimed: ${state['total_claimed']:,.2f}
Total Approved: ${state['total_approved']:,.2f}
Total Deduction: ${variance_total:,.2f}

ERP Findings:
{json.dumps([d.model_dump() for d in discrepancies], indent=2)}

Governing Contract Clause:
{state['rag_contract_clause']}
"""
        response = llm.invoke(prompt)
        explanation = response.content.strip()
    else:
        bullet_reasons = []
        for d in discrepancies:
            if "ERR_GRN_QTY_SHORTAGE" in d.discrepancy_code:
                short_units = d.claimed_qty - d.erp_grn_qty
                bullet_reasons.append(
                    f"• Quantity Adjustment ({d.sku}): You billed for {d.claimed_qty} units, whereas our warehouse "
                    f"received {d.erp_grn_qty} units in good condition ({short_units} units were damaged upon arrival and rejected at the dock)."
                )
            if "ERR_PRICE_VAR_EXCEEDED" in d.discrepancy_code:
                diff = d.claimed_unit_price - d.erp_unit_price
                bullet_reasons.append(
                    f"• Unit Price Adjustment ({d.sku}): The billed rate of ${d.claimed_unit_price:.2f} per unit exceeds "
                    f"our contracted Purchase Order price of ${d.erp_unit_price:.2f} by ${diff:.2f} per unit."
                )
            if "ERR_SKU_NOT_ON_PO" in d.discrepancy_code:
                bullet_reasons.append(
                    f"• Unlisted Item ({d.sku}): This item was not included on Purchase Order {claim.po_number}."
                )

        reasons_block = "\n".join(bullet_reasons)
        explanation = (
            f"Dear {supplier_name} Billing Team,\n\n"
            f"Thank you for submitting Invoice #{claim.invoice_number} referencing Purchase Order {claim.po_number}. "
            f"We have completed our 3-way verification and approved a settlement of ${state['total_approved']:,.2f} "
            f"out of your claimed ${state['total_claimed']:,.2f} (a net adjustment of ${variance_total:,.2f}).\n\n"
            f"Reason for Adjustment:\n{reasons_block}\n\n"
            f"Contractual Basis:\n{state['rag_contract_clause']}\n\n"
            f"Please issue a revised credit memo for ${variance_total:,.2f} or contact our Accounts Receivable desk if you would like a copy of the signed Goods Receipt inspection log."
        )

    trace = state["execution_trace"] + [
        "[4. Justification Agent] Generated supplier-friendly natural language explanation and queued for Analyst Review."
    ]
    return {
        "natural_language_justification": explanation,
        "status": "DISCREPANCY_REVIEW",
        "execution_trace": trace,
    }


def node_auto_approve(state: ClaimGraphState) -> dict:
    claim = state["canonical_claim"]
    msg = (
        f"Invoice #{claim.invoice_number} (PO {claim.po_number}) passed 100% 3-way matching "
        f"for ${state['total_approved']:,.2f}. Scheduled for immediate payment."
    )
    trace = state["execution_trace"] + [
        "[3. Auto-Approval Router] Zero discrepancies detected. Claim auto-approved for Straight-Through Processing (STP)."
    ]
    return {
        "rag_contract_clause": "N/A - Full 3-Way Match",
        "natural_language_justification": msg,
        "status": "AUTO_APPROVED",
        "execution_trace": trace,
    }


def node_persist(state: ClaimGraphState) -> dict:
    claim = state["canonical_claim"]
    conn = get_connection()
    cur = conn.cursor()

    now_iso = datetime.now().isoformat()
    resolved_iso = now_iso if state["status"] == "AUTO_APPROVED" else None

    cur.execute(
        """INSERT INTO claims_header
           (claim_id, supplier_id, invoice_number, po_number, file_format, raw_content,
            total_claimed_amount, total_approved_amount, status, created_at, resolved_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            state["claim_id"],
            claim.supplier_id,
            claim.invoice_number,
            claim.po_number,
            claim.file_format,
            state["raw_text"],
            state["total_claimed"],
            state["total_approved"],
            state["status"],
            now_iso,
            resolved_iso,
        ),
    )

    for r in state["reconciliation_results"]:
        cur.execute(
            """INSERT INTO claim_line_items
               (claim_id, sku, claimed_qty, erp_po_qty, erp_grn_qty, claimed_unit_price,
                erp_unit_price, variance_amount, discrepancy_code)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                state["claim_id"],
                r.sku,
                r.claimed_qty,
                r.erp_po_qty,
                r.erp_grn_qty,
                r.claimed_unit_price,
                r.erp_unit_price,
                r.variance_amount,
                r.discrepancy_code,
            ),
        )

    raw_codes = "; ".join([f"{r.discrepancy_code}: {r.erp_detail}" for r in state["reconciliation_results"]])
    cur.execute(
        """INSERT INTO discrepancy_justifications
           (claim_id, erp_raw_codes, rag_contract_clause, natural_language_explanation, analyst_notes, approved_by_human)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            state["claim_id"],
            raw_codes,
            state["rag_contract_clause"],
            state["natural_language_justification"],
            "Auto-processed" if state["status"] == "AUTO_APPROVED" else "Awaiting analyst review",
            1 if state["status"] == "AUTO_APPROVED" else 0,
        ),
    )

    conn.commit()
    conn.close()

    trace = state["execution_trace"] + [
        f"[5. Persistence Layer] Saved claim {state['claim_id']} to SQLite with status '{state['status']}'."
    ]
    return {"execution_trace": trace}


def route_after_reconcile(state: ClaimGraphState) -> str:
    if state["has_discrepancy"]:
        return "policy_rag"
    return "auto_approve"


def build_claims_graph():
    workflow = StateGraph(ClaimGraphState)

    workflow.add_node("ingest", node_ingest)
    workflow.add_node("reconcile", node_reconcile)
    workflow.add_node("policy_rag", node_policy_rag)
    workflow.add_node("justify", node_generate_justification)
    workflow.add_node("auto_approve", node_auto_approve)
    workflow.add_node("persist", node_persist)

    workflow.set_entry_point("ingest")
    workflow.add_edge("ingest", "reconcile")
    workflow.add_conditional_edges(
        "reconcile",
        route_after_reconcile,
        {
            "policy_rag": "policy_rag",
            "auto_approve": "auto_approve",
        },
    )
    workflow.add_edge("policy_rag", "justify")
    workflow.add_edge("justify", "persist")
    workflow.add_edge("auto_approve", "persist")
    workflow.add_edge("persist", END)

    return workflow.compile()