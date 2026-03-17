"""
Grafo LangGraph del Integration Governance Agent.

Estado actual: un único nodo (Discoverer).
Se irán añadiendo Mapper, Governance y Generator en siguientes fases.
"""

from typing import TypedDict, Optional
from langgraph.graph import StateGraph, END
from agents.discoverer import discoverer_node


class AgentState(TypedDict):
    user_request: str
    schemas: Optional[dict]
    proposed_mapping: Optional[list]
    governance_decisions: Optional[list]
    ciba_transaction_id: Optional[str]
    generated_code: Optional[str]
    deployed_endpoint: Optional[str]
    audit_log: Optional[list]


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("discoverer", discoverer_node)
    graph.set_entry_point("discoverer")
    graph.add_edge("discoverer", END)
    return graph.compile()


graph = build_graph()
