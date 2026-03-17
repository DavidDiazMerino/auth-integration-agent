import os
import secrets
import uuid
import base64
import json as _json
import httpx
from urllib.parse import urlencode
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Integration Governance Agent")

def _get_graph():
    from agents.graph import graph
    return graph

DOMAIN = os.getenv("AUTH0_DOMAIN")
CLIENT_ID = os.getenv("AUTH0_CLIENT_ID")
CLIENT_SECRET = os.getenv("AUTH0_CLIENT_SECRET")
CALLBACK_URL = os.getenv("AUTH0_CALLBACK_URL", "http://localhost:8000/auth/callback")
CONNECT_CALLBACK_URL = os.getenv("AUTH0_CONNECT_CALLBACK_URL", "http://localhost:8000/auth/connect-callback")

# Scopes requeridos por conexión para el connect flow
_CONNECTION_SCOPES = {
    "github": ["public_repo", "admin:repo_hook"],
    "sign-in-with-slack": ["channels:read", "chat:write"],
}

_oauth_state: dict = {}
_user_session: dict = {}


async def _get_my_account_token() -> str:
    """Obtiene un access token para la My Account API usando el refresh_token del usuario (MRRT).
    Audience con trailing slash y scopes explícitos — requerido por Auth0.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://{DOMAIN}/oauth/token",
            json={
                "grant_type": "refresh_token",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "refresh_token": _user_session["refresh_token"],
                "audience": f"https://{DOMAIN}/me/",
                "scope": "openid offline_access create:me:connected_accounts read:me:connected_accounts delete:me:connected_accounts",
            },
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"My Account API token error: {resp.text}")
    return resp.json()["access_token"]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/debug/connections")
async def debug_connections():
    """Debug: lista las conexiones disponibles en Token Vault para este usuario."""
    if not _user_session.get("refresh_token"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = await _get_my_account_token()
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"https://{DOMAIN}/me/v1/connected-accounts/connections",
            headers={"Authorization": f"Bearer {token}"},
        )
    return {"status": r.status_code, "body": r.json()}


@app.get("/auth/login")
def login():
    """Redirect user to Auth0 for login. Requests offline_access to get a refresh_token."""
    state = secrets.token_urlsafe(16)
    _oauth_state["state"] = state

    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": CALLBACK_URL,
        "scope": "openid profile email offline_access",
        "state": state,
    }
    return RedirectResponse(f"https://{DOMAIN}/authorize?{urlencode(params)}")


@app.get("/auth/callback")
async def callback(
    state: str,
    code: str = None,
    error: str = None,
    error_description: str = None,
):
    """Exchange auth code for tokens. Stores refresh_token for agent use."""
    if error:
        raise HTTPException(status_code=400, detail=f"Auth0 error: {error} — {error_description}")

    if state != _oauth_state.get("state"):
        raise HTTPException(status_code=400, detail="Invalid state")

    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://{DOMAIN}/oauth/token",
            json={
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "code": code,
                "redirect_uri": CALLBACK_URL,
            },
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Auth0 error: {resp.text}")

    tokens = resp.json()
    _user_session["refresh_token"] = tokens.get("refresh_token")
    _user_session["access_token"] = tokens.get("access_token")
    _user_session["id_token"] = tokens.get("id_token")

    payload = _user_session["id_token"].split(".")[1]
    payload += "=" * (4 - len(payload) % 4)
    claims = _json.loads(base64.b64decode(payload))
    _user_session["user_id"] = claims.get("sub")

    return JSONResponse({
        "status": "authenticated",
        "user_id": _user_session["user_id"],
        "has_refresh_token": bool(_user_session.get("refresh_token")),
    })


@app.get("/auth/session")
def session():
    return {
        "authenticated": bool(_user_session.get("user_id")),
        "user_id": _user_session.get("user_id"),
        "has_refresh_token": bool(_user_session.get("refresh_token")),
        "connected_accounts": _user_session.get("connected_accounts", []),
    }


@app.get("/auth/connect/{connection}")
async def connect_account(connection: str):
    """Inicia el flujo My Account API para vincular una cuenta externa (github, sign-in-with-slack)."""
    if not _user_session.get("refresh_token"):
        raise HTTPException(status_code=401, detail="Not authenticated. Visit /auth/login first.")

    my_account_token = await _get_my_account_token()
    state = secrets.token_urlsafe(16)
    scopes = _CONNECTION_SCOPES.get(connection, [])

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://{DOMAIN}/me/v1/connected-accounts/connect",
            headers={"Authorization": f"Bearer {my_account_token}"},
            json={
                "connection": connection,
                "redirect_uri": CONNECT_CALLBACK_URL,
                "state": state,
                "scopes": scopes,
            },
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Connect init error: {resp.text}")

    data = resp.json()
    _oauth_state["connect_state"] = state
    _oauth_state["connect_auth_session"] = data["auth_session"]
    _oauth_state["connect_connection"] = connection

    return RedirectResponse(data["connect_uri"])


@app.get("/auth/connect-callback")
async def connect_callback(
    connect_code: str = None,
    state: str = None,
    error: str = None,
    error_description: str = None,
):
    """Callback tras autorizar una cuenta externa en Auth0."""
    if error:
        raise HTTPException(status_code=400, detail=f"Connect error: {error} — {error_description}")

    if state != _oauth_state.get("connect_state"):
        raise HTTPException(status_code=400, detail="Invalid connect state")

    if not connect_code:
        raise HTTPException(status_code=400, detail="Missing connect_code")

    my_account_token = await _get_my_account_token()

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://{DOMAIN}/me/v1/connected-accounts/complete",
            headers={"Authorization": f"Bearer {my_account_token}"},
            json={
                "auth_session": _oauth_state["connect_auth_session"],
                "connect_code": connect_code,
                "redirect_uri": CONNECT_CALLBACK_URL,
            },
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Connect complete error: {resp.text}")

    connection = _oauth_state.get("connect_connection", "unknown")
    connected = _user_session.setdefault("connected_accounts", [])
    if connection not in connected:
        connected.append(connection)

    return JSONResponse({
        "status": "connected",
        "connection": connection,
        "connected_accounts": connected,
    })


class RunRequest(BaseModel):
    user_request: str


@app.post("/run")
async def run(req: RunRequest):
    """Arranca el grafo LangGraph con la user_request."""
    if not _user_session.get("refresh_token"):
        raise HTTPException(status_code=401, detail="Not authenticated. Visit /auth/login first.")

    config = {
        "configurable": {
            "thread_id": str(uuid.uuid4()),
            "_credentials": {
                "refresh_token": _user_session["refresh_token"],
            },
        }
    }

    result = await _get_graph().ainvoke(
        {"user_request": req.user_request},
        config=config,
    )
    return result
