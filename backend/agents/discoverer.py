"""
Agente Discoverer — nodo 1 del grafo LangGraph.

Recupera tokens de Token Vault y llama a las APIs reales de GitHub y Slack
para extraer los schemas que el Mapper usará después.
"""

import re
import uuid
import httpx
from pydantic import BaseModel
from langchain_core.tools import StructuredTool
from langchain_core.runnables import RunnableConfig
from auth0_ai_langchain.token_vault import get_access_token_from_token_vault

from auth.token_vault import with_github_read, with_slack_read


# ---------------------------------------------------------------------------
# GitHub tool
# ---------------------------------------------------------------------------

class GitHubRepoInput(BaseModel):
    owner: str
    repo: str


async def _github_fetch(owner: str, repo: str) -> dict:
    token = get_access_token_from_token_vault()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        resp.raise_for_status()
        d = resp.json()

    return {
        "full_name": d["full_name"],
        "description": d.get("description"),
        "default_branch": d["default_branch"],
        "private": d["private"],
        "hooks_url": d["hooks_url"],
        "fields": {
            "pull_request.title": {"type": "string", "example": "Fix login bug"},
            "pull_request.number": {"type": "integer", "example": 42},
            "pull_request.html_url": {"type": "string", "example": f"https://github.com/{d['full_name']}/pull/42"},
            "pull_request.user.login": {"type": "string", "pii": True, "example": "octocat"},
            "pull_request.head.ref": {"type": "string", "example": "feature/my-branch"},
            "pull_request.base.ref": {"type": "string", "example": d["default_branch"]},
            "pull_request.state": {"type": "string", "example": "open"},
        },
    }


github_schema_tool = with_github_read(
    StructuredTool.from_function(
        coroutine=_github_fetch,
        name="fetch_github_schema",
        description="Fetch GitHub repo metadata and available PR fields",
        args_schema=GitHubRepoInput,
    )
)


# ---------------------------------------------------------------------------
# Slack tool
# ---------------------------------------------------------------------------

class SlackInput(BaseModel):
    pass


async def _slack_fetch() -> dict:
    token = get_access_token_from_token_vault()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://slack.com/api/conversations.list",
            headers={"Authorization": f"Bearer {token}"},
            params={"limit": 100, "exclude_archived": "true"},
        )
        resp.raise_for_status()
        data = resp.json()

    if not data.get("ok"):
        raise RuntimeError(f"Slack API error: {data.get('error')}")

    channels = [
        {"id": c["id"], "name": c["name"], "is_member": c.get("is_member", False)}
        for c in data.get("channels", [])
    ]
    return {
        "channels": channels,
        "fields": {
            "channel.id": {"type": "string", "example": "C01234567"},
            "channel.name": {"type": "string", "example": "incidencias"},
        },
    }


slack_channels_tool = with_slack_read(
    StructuredTool.from_function(
        coroutine=_slack_fetch,
        name="fetch_slack_channels",
        description="Fetch available Slack channels",
        args_schema=SlackInput,
    )
)


# ---------------------------------------------------------------------------
# LangGraph node
# ---------------------------------------------------------------------------

def _parse_repo(user_request: str) -> tuple[str, str]:
    """Extrae owner/repo de la user_request. Formato esperado: 'owner/repo'."""
    match = re.search(r"([\w.-]+)/([\w.-]+)", user_request)
    if not match:
        raise ValueError(f"No se encontró owner/repo en: {user_request!r}")
    return match.group(1), match.group(2)


def _tool_call(tool_name: str, args: dict) -> dict:
    """Formato requerido por tools con InjectedToolCallId."""
    return {
        "type": "tool_call",
        "name": tool_name,
        "args": args,
        "id": str(uuid.uuid4()),
    }


async def discoverer_node(state: dict, config: RunnableConfig) -> dict:
    owner, repo = _parse_repo(state["user_request"])

    github_schema = await github_schema_tool.ainvoke(
        _tool_call("fetch_github_schema", {"owner": owner, "repo": repo}), config
    )
    slack_schema = await slack_channels_tool.ainvoke(
        _tool_call("fetch_slack_channels", {}), config
    )

    return {
        "schemas": {
            "github": github_schema,
            "slack": slack_schema,
        }
    }
