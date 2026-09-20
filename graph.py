"""Общий клиент для Microsoft Graph: токен + GET/POST/PATCH с пагинацией."""
import os

import msal
import requests
from dotenv import load_dotenv

load_dotenv()

TENANT_ID = os.environ["TENANT_ID"]
CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]

GRAPH = "https://graph.microsoft.com/v1.0"

_app = msal.ConfidentialClientApplication(
    CLIENT_ID,
    authority=f"https://login.microsoftonline.com/{TENANT_ID}",
    client_credential=CLIENT_SECRET,
)


def _token() -> str:
    # MSAL сам кэширует токен и обновляет его, когда он истекает
    result = _app.acquire_token_for_client(
        scopes=["https://graph.microsoft.com/.default"]
    )
    if "access_token" not in result:
        raise RuntimeError(
            f"Не удалось получить токен: {result.get('error')} — "
            f"{result.get('error_description')}"
        )
    return result["access_token"]


def _headers() -> dict:
    return {"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"}


def get_all(path: str, params: dict | None = None) -> list[dict]:
    """GET со всеми страницами. Graph отдаёт до 100 записей и ссылку на следующую."""
    url = f"{GRAPH}{path}"
    items = []
    while url:
        r = requests.get(url, headers=_headers(), params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        items.extend(data.get("value", []))
        url = data.get("@odata.nextLink")
        params = None  # nextLink уже содержит все параметры
    return items


def get_one(path: str, params: dict | None = None) -> dict | None:
    """GET одного объекта. Вернёт None, если его нет (404)."""
    r = requests.get(f"{GRAPH}{path}", headers=_headers(), params=params, timeout=30)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def put(path: str, body: dict) -> None:
    r = requests.put(f"{GRAPH}{path}", headers=_headers(), json=body, timeout=30)
    if not r.ok:
        raise RuntimeError(f"PUT {path} -> {r.status_code}: {r.text}")


def post(path: str, body: dict) -> dict:
    r = requests.post(f"{GRAPH}{path}", headers=_headers(), json=body, timeout=30)
    if not r.ok:
        raise RuntimeError(f"POST {path} -> {r.status_code}: {r.text}")
    return r.json() if r.content else {}


def delete(path: str) -> None:
    r = requests.delete(f"{GRAPH}{path}", headers=_headers(), timeout=30)
    if not r.ok:
        raise RuntimeError(f"DELETE {path} -> {r.status_code}: {r.text}")


def patch(path: str, body: dict) -> None:
    r = requests.patch(f"{GRAPH}{path}", headers=_headers(), json=body, timeout=30)
    if not r.ok:
        raise RuntimeError(f"PATCH {path} -> {r.status_code}: {r.text}")
