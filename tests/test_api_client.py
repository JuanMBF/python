import pytest
import requests

from dashboard.api_client import ApiError, HelpDeskClient


def _fake_response(status_code: int, body: bytes, content_type: str) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = body
    response.headers["Content-Type"] = content_type
    return response


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    def make(status_code: int, body: bytes, content_type: str = "application/json") -> HelpDeskClient:
        api = HelpDeskClient(base_url="http://api.test/api/v1")
        response = _fake_response(status_code, body, content_type)
        monkeypatch.setattr(api._session, "request", lambda *args, **kwargs: response)
        return api

    return make


def test_json_response_is_returned(client) -> None:
    assert client(200, b'{"id": 1}').me() == {"id": 1}


def test_validation_errors_are_joined(client) -> None:
    body = b'{"detail": [{"loc": ["body", "title"], "msg": "muy corto"}]}'
    with pytest.raises(ApiError) as error:
        client(422, body).create_ticket(title="x")
    assert error.value.status_code == 422
    assert error.value.message == "title: muy corto"


def test_non_json_success_response_is_an_api_error(client) -> None:
    # e.g. HELPDESK_API_URL pointing to the Streamlit app or a proxy page instead of the API.
    api = client(200, b"<!doctype html><html></html>", "text/html")
    with pytest.raises(ApiError) as error:
        api.me()
    assert error.value.status_code == 200
    assert "http://api.test/api/v1" in error.value.message


@pytest.mark.parametrize(("email", "password"), [("", ""), ("   ", "Demo1234!"), ("ana@example.com", "")])
def test_login_with_empty_fields_does_not_call_the_api(client, email: str, password: str) -> None:
    # The API rejected it with "username: Field required; password: Field required".
    api = client(200, b'{"access_token": "token"}')
    api._session.request = lambda *args, **kwargs: pytest.fail("no debería llamar a la API")

    with pytest.raises(ApiError) as error:
        api.login(email, password)
    assert error.value.message == "Completá el email y la contraseña"
    assert api.token is None


def test_error_with_json_that_is_not_an_object_keeps_the_status(client) -> None:
    with pytest.raises(ApiError) as error:
        client(502, b'["bad gateway"]').me()
    assert error.value.message == "Error 502"
