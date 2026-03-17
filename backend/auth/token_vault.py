"""
Token Vault wrappers — 4 conexiones, least privilege por agente.

Uso dentro de un tool:
    from auth0_ai_langchain.token_vault import get_access_token_from_token_vault
    token = get_access_token_from_token_vault()
"""

from auth0_ai_langchain.auth0_ai import Auth0AI

auth0_ai = Auth0AI()  # lee AUTH0_DOMAIN / AUTH0_CLIENT_ID / AUTH0_CLIENT_SECRET del entorno

# Discoverer — lectura de repos GitHub
with_github_read = auth0_ai.with_token_vault(
    connection="github",
    scopes=["public_repo"],
)

# Discoverer — lectura de canales Slack
with_slack_read = auth0_ai.with_token_vault(
    connection="sign-in-with-slack",
    scopes=["channels:read"],
)

# Generator — postear mensajes en Slack
with_slack_post = auth0_ai.with_token_vault(
    connection="sign-in-with-slack",
    scopes=["chat:write"],
)

# Generator — registrar webhooks en GitHub
with_github_webhook = auth0_ai.with_token_vault(
    connection="github",
    scopes=["admin:repo_hook"],
)
