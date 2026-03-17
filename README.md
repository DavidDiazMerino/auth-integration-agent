# Integration Governance Agent

An autonomous integration agent that generates webhook-based connectors between systems — with explicit security governance and user consent via mobile push notifications.

Built for the **"Authorized to Act: Auth0 for AI Agents"** hackathon (Devpost, April 2026).

## The Problem

When connecting two systems, either a developer does it manually (losing architectural decisions in their head), or an automatic tool does it skipping security. This agent forces explicit recording of every decision before generating anything, with autonomous PII/scope detection and user consent for actions with real consequences.

## Demo

> "When a PR is opened in my GitHub repo, post a message to Slack #incidencias."

The agent discovers schemas from both systems, proposes field mappings, detects PII and scope issues autonomously, requests explicit approval via push notification to the user's phone (CIBA), and generates + deploys a working Go webhook — with a full audit trail of every decision.

## Architecture

Four LangGraph agents run sequentially:

| Agent | Role | Tokens |
|-------|------|--------|
| **Discoverer** | Fetches GitHub repo schema + Slack channels | `github` (read), `sign-in-with-slack` (channels:read) |
| **Mapper** | Proposes field mappings between schemas | — |
| **Governance** | Detects PII/scope issues, triggers CIBA approval | — (no write tokens by design) |
| **Generator** | Renders Go code, compiles, deploys, registers webhook | `github` (admin:repo_hook), `sign-in-with-slack` (chat:write) |

Each agent only gets the tokens it needs — least privilege per agent, not per application. Tokens are managed by [Auth0 Token Vault](https://auth0.com/docs/secure/tokens/token-vault) and never logged, passed between agents, or exposed to the frontend.

## Stack

- **Orchestration:** LangGraph (Python)
- **Backend:** FastAPI + SSE
- **Auth:** Auth0 AI SDK — Token Vault + CIBA
- **Generated connector:** Go (static binary, ~10MB Docker image)
- **Frontend:** Next.js (3 screens: Chat, Decisions, Audit)

## Getting Started

### Prerequisites

- Python 3.12+
- An Auth0 tenant with:
  - A Regular Web Application configured
  - GitHub and Slack social connections set up as Connected Accounts for Token Vault
  - My Account API activated with `connected_accounts` scopes granted to your app
  - MRRT enabled for the My Account API

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your values
uvicorn main:app --reload
```

### Auth Flow

1. **Login:** `GET /auth/login` — OAuth2 with Auth0 (Google)
2. **Connect GitHub:** `GET /auth/connect/github` — links GitHub account to Token Vault
3. **Connect Slack:** `GET /auth/connect/sign-in-with-slack` — links Slack account to Token Vault
4. **Run agent:** `POST /run` with `{"user_request": "When a PR is opened in owner/repo, post to #channel"}`

Steps 2 and 3 only need to be done once per user. After that, Token Vault handles token exchange automatically.

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/auth/login` | Start OAuth2 login |
| GET | `/auth/callback` | Auth0 callback |
| GET | `/auth/session` | Current session state |
| GET | `/auth/connect/{connection}` | Initiate Token Vault account connection |
| GET | `/auth/connect-callback` | Token Vault connect callback |
| POST | `/run` | Run the agent graph |

## Project Structure

```
/
├── backend/
│   ├── main.py              # FastAPI app + auth endpoints
│   ├── requirements.txt
│   ├── agents/
│   │   ├── discoverer.py    # Discoverer node (GitHub + Slack)
│   │   └── graph.py         # LangGraph state + compiled graph
│   └── auth/
│       ├── token_vault.py   # Token Vault wrappers (4 connections)
│       └── ciba.py          # CIBA governance approval decorator
└── frontend/                # Next.js (in progress)
```

## How Token Vault Works Here

Auth0 Token Vault stores OAuth tokens for external services (GitHub, Slack) per user. When an agent tool needs to call an API:

1. The tool is wrapped with `with_token_vault(connection="github", scopes=[...])`
2. At runtime, the SDK exchanges the user's Auth0 `refresh_token` for a GitHub access token
3. Inside the tool, `get_access_token_from_token_vault()` returns the token
4. The token never leaves the tool scope — it's not stored, logged, or passed anywhere

## How CIBA Works Here

When the Governance agent detects a HIGH severity issue (PII exposure, excessive scope):

1. LangGraph execution pauses via a graph interrupt
2. Auth0 sends a push notification to the user's mobile device
3. User approves or rejects from their phone
4. Consent is recorded in Auth0 with a timestamp
5. Graph resumes with the decision recorded in the audit log
