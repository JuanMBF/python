"""Thin HTTP client for the HelpDesk Pro REST API."""

import os
from typing import Any

import requests

DEFAULT_API_URL = "http://localhost:8000/api/v1"


class ApiError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class HelpDeskClient:
    def __init__(self, base_url: str | None = None, token: str | None = None, timeout: float = 10) -> None:
        self.base_url = (base_url or os.getenv("HELPDESK_API_URL", DEFAULT_API_URL)).rstrip("/")
        self.token = token
        self.timeout = timeout
        self._session = requests.Session()

    # --- low level ---------------------------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = kwargs.pop("headers", {})
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            response = self._session.request(
                method, f"{self.base_url}{path}", headers=headers, timeout=self.timeout, **kwargs
            )
        except requests.RequestException as exc:
            raise ApiError(0, f"No se pudo conectar con la API en {self.base_url}") from exc

        if response.status_code >= 400:
            raise ApiError(response.status_code, _error_message(response))
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            # Something answered, but not the API (e.g. HELPDESK_API_URL points to another app).
            raise ApiError(
                response.status_code, f"La respuesta de {self.base_url} no es de la API de HelpDesk Pro"
            ) from exc

    # --- auth --------------------------------------------------------------------------------

    def login(self, email: str, password: str) -> str:
        # The API would answer 422 "username: Field required", and the form field is called "Email".
        if not email.strip() or not password:
            raise ApiError(422, "Completá el email y la contraseña")
        data = self._request("POST", "/auth/login", data={"username": email, "password": password})
        self.token = data["access_token"]
        return self.token

    def me(self) -> dict:
        return self._request("GET", "/auth/me")

    # --- tickets -----------------------------------------------------------------------------

    def list_tickets(self, **params: Any) -> dict:
        clean = {key: value for key, value in params.items() if value not in (None, [], "", False)}
        return self._request("GET", "/tickets", params=clean)

    def get_ticket(self, ticket_id: int) -> dict:
        return self._request("GET", f"/tickets/{ticket_id}")

    def create_ticket(self, **payload: Any) -> dict:
        return self._request("POST", "/tickets", json=payload)

    def update_ticket(self, ticket_id: int, **changes: Any) -> dict:
        return self._request("PATCH", f"/tickets/{ticket_id}", json=changes)

    def add_comment(self, ticket_id: int, body: str, is_internal: bool = False) -> dict:
        return self._request(
            "POST", f"/tickets/{ticket_id}/comments", json={"body": body, "is_internal": is_internal}
        )

    # --- users & stats -----------------------------------------------------------------------

    def list_users(self, roles: list[str] | None = None, is_active: bool | None = None) -> list[dict]:
        params: dict[str, Any] = {"role": roles or []}
        if is_active is not None:
            params["is_active"] = is_active
        return self._request("GET", "/users", params=params)

    def create_user(self, **payload: Any) -> dict:
        return self._request("POST", "/users", json=payload)

    def update_user(self, user_id: int, **changes: Any) -> dict:
        return self._request("PATCH", f"/users/{user_id}", json=changes)

    def stats(self, days: int = 30) -> dict:
        return self._request("GET", "/stats/overview", params={"days": days})


def _error_message(response: requests.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"Error {response.status_code}"
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, list):  # FastAPI validation errors
        return "; ".join(_format_validation_error(error) for error in detail)
    return str(detail or f"Error {response.status_code}")


def _format_validation_error(error: dict) -> str:
    field = error.get("loc", ["", ""])[-1]
    return f"{field}: {error.get('msg', 'valor inválido')}"
