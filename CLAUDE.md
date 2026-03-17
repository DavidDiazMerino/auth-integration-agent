# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

Hackathon "Authorized to Act: Auth0 for AI Agents" (Devpost, deadline April 7 2026, $10K). Required: use Auth0 for AI Agents Token Vault.

Dual purpose: win the hackathon AND build a real POC of an autonomous integration platform with decision governance — a broader product idea in parallel development.

## The Problem It Solves

When someone connects two systems, either a developer does it manually (losing architectural decisions in their head), or an automatic tool does it skipping security. This system forces explicit recording of all decisions before generating anything, with autonomous governance and explicit user consent for actions with real consequences.

## Demo Use Case

"When a PR is opened in my GitHub repo X, post a message to Slack channel #incidencias."

A real flow the author uses. Simple enough for any judge but with enough surface to demonstrate all key concepts.

## Running the Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn main:app --reload
```

Runs on `http://localhost:8000`. Visit `/auth/login` to start the OAuth2 flow.

## Architecture

Four LangGraph agents run sequentially, each with scoped Token Vault credentials:

1. **Discoverer** — Fetches GitHub repo schema (`with_github_read`) and Slack channel schema (`with_slack_read`). Read-only, never writes.
2. **Mapper** — Takes discovered schemas, proposes field mappings (`PR.title → text`, `PR.user.login → author`, `PR.head.ref → branch`)
3. **Governance** — The central differentiator. Autonomously detects PII (e.g. `PR.user.login`) and excessive scope (e.g. `repo` when only one repo is needed), generates explicit decisions with severity. If HIGH severity → pauses the graph and triggers CIBA push notification to user's mobile. Graph resumes after approval. Consent recorded in Auth0 with timestamp.
4. **Generator** — Takes approved mapping + resolved decisions, renders Jinja2 template → Go code, compiles static binary, Docker build, deploys to Trantor via Docker API, registers GitHub webhook using `with_github_webhook`.

### LangGraph Graph State

```python
{
  "user_request": str,
  "schemas": {"github": {...}, "slack": {...}},
  "proposed_mapping": [...],
  "governance_decisions": [
    {
      "id": "D1",
      "type": "PII",
      "field": "user.login",
      "status": "pending|approved|rejected",
      "approved_by": str,
      "approved_at": str
    },
    {
      "id": "D2",
      "type": "SCOPE",
      "current": "repo",
      "recommended": "repo:read",
      "status": "pending|approved|rejected"
    }
  ],
  "ciba_transaction_id": str,
  "generated_code": str,
  "deployed_endpoint": str,
  "audit_log": [...]
}
```

## Key Files

- `backend/main.py` — FastAPI app: OAuth2 login, callback, session endpoints
- `backend/auth/token_vault.py` — Token Vault wrappers per agent (`with_github_read`, `with_slack_read`, `with_slack_post`, `with_github_webhook`)
- `backend/auth/ciba.py` — `@with_governance_approval` decorator that wraps LangGraph tools with CIBA auth
- `backend/agents/` — LangGraph agent nodes (to be implemented)
- `frontend/` — Next.js UI (to be implemented)

## Token Vault Least-Privilege Model

Each agent can only request its own token. Governance has no write tokens. Discoverer cannot post. Least privilege per agent, not per application.

| Agent | Connection | Scopes |
|-------|-----------|--------|
| Discoverer | `github-discoverer` | `repo:read` |
| Discoverer | `slack-reader` | `channels:read` |
| Generator | `slack-poster` | `chat:write` (restricted to #incidencias) |
| Generator | `github-generator` | `admin:repo_hook` |

## CIBA Pattern

The governance agent wraps decision tools with `@with_governance_approval`. When severity is HIGH, LangGraph execution pauses and Auth0 sends a push notification to the user's mobile. The graph resumes on approval. LangGraph config must carry `configurable.user_id` (Auth0 `sub` claim).

## Frontend — 3 Screens Only

1. **Chat** — Natural language input, streaming graph logs via SSE
2. **Decisions** — Governance panel with detected alerts, CIBA status
3. **Audit** — Active tokens per agent with scopes, decision log with timestamps

Backend streams to frontend via SSE (FastAPI + `sse-starlette`).

## Auth Flow — Account Connection (My Account API)

Before the agents can call GitHub/Slack, the user must connect each external account once via Token Vault's My Account API:

1. `GET /auth/connect/github` → backend calls `POST https://{domain}/me/v1/connected-accounts/connect` → redirects user to GitHub OAuth
2. User approves on GitHub → Auth0 redirects to `GET /auth/connect-callback?connect_code=...`
3. Backend calls `POST https://{domain}/me/v1/connected-accounts/complete` → connection stored in Token Vault

**Critical Auth0 API details learned in production:**
- My Account API audience **must have trailing slash**: `https://{domain}/me/` (without it returns "Bad HTTP authentication header format")
- MRRT token exchange must explicitly include `create:me:connected_accounts read:me:connected_accounts delete:me:connected_accounts` scopes
- GitHub connect request requires `scopes: ["public_repo", "admin:repo_hook"]` (cannot be empty)
- `POST /me/v1/connected-accounts/connect` returns `auth_session` + `connect_uri` (redirect target)
- Auth0 free tier rate limits this API aggressively during development

After connecting, Token Vault exchanges the Auth0 `refresh_token` for GitHub/Slack access tokens automatically when `get_access_token_from_token_vault()` is called inside a tool.

## Environment Variables

Required in `.env`:
- `AUTH0_DOMAIN`
- `AUTH0_CLIENT_ID`
- `AUTH0_CLIENT_SECRET`
- `AUTH0_AUDIENCE`
- `AUTH0_CALLBACK_URL` (defaults to `http://localhost:8000/auth/callback`)
- `AUTH0_CONNECT_CALLBACK_URL` (defaults to `http://localhost:8000/auth/connect-callback`)

## Generated Go Code

The Generator produces Go source (not meant to be human-maintained), compiled to a static binary (~10MB Docker image), deployed to Trantor. The generated Go **must always include comments** with the approved decisions, who approved them, and when.

## Instructions for Claude Code

- Work in `/backend` for Python backend and `/frontend` for Next.js. Never mix dependencies between the two environments.
- The Governance agent is the most important node — when in doubt about design, prioritize making decisions explicit and audited above all else.
- Token Vault tokens are **never logged, never passed between agents, never exposed to the frontend**.
- Before implementing any agent, verify that `token_vault.py` can correctly retrieve the token for that connection.
- When in doubt about token scope, always choose the most restrictive one.
