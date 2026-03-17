"""
CIBA (Client-Initiated Backchannel Authentication) for the Governance agent.

When a governance decision requires explicit user approval, we wrap the decision tool
with with_governance_approval. The user gets a push notification on their phone.
Auth0 records the approval with a timestamp.

Usage:
    from auth0_ai_langchain.async_authorization import get_async_authorization_credentials
    from langchain_core.runnables import ensure_config

    @with_governance_approval(binding_message=lambda decision_id, description: f"Approve: {description}")
    def approve_decision_tool(decision_id: str, description: str) -> str:
        # if we reach here, user approved on their phone
        return "approved"
"""

import os
from auth0_ai_langchain.auth0_ai import Auth0AI
from langchain_core.runnables import ensure_config

auth0_ai = Auth0AI()


def _get_user_id(*_, **__) -> str:
    """Reads user_id (Auth0 sub) from LangGraph config."""
    return ensure_config().get("configurable", {}).get("user_id", "")


def with_governance_approval(binding_message):
    """
    Decorator factory. binding_message is a callable(decision_id, description) -> str
    that builds the text shown in the push notification.
    """
    return auth0_ai.with_async_authorization(
        scopes=["openid"],
        audience=os.getenv("AUTH0_AUDIENCE"),
        user_id=_get_user_id,
        binding_message=binding_message,
        on_authorization_request="interrupt",  # pauses LangGraph, resumes on approval
    )
