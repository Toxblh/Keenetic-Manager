import pytest
import requests_mock
import requests
from unittest.mock import patch, MagicMock

from src.api.keenetic_router import KeeneticRouter


class TestKeeneticRouterInit:
    def test_base_url_without_protocol(self):
        router = KeeneticRouter("192.168.1.1", "admin", "pass", "test")
        assert router.base_url == "http://192.168.1.1"

    def test_base_url_with_trailing_slash(self):
        router = KeeneticRouter("192.168.1.1/", "admin", "pass", "test")
        assert router.base_url == "http://192.168.1.1"

    def test_base_url_already_has_protocol(self):
        router = KeeneticRouter("http://192.168.1.1", "admin", "pass", "test")
        assert router.base_url == "http://192.168.1.1"

    def test_base_url_preserves_https(self):
        router = KeeneticRouter("https://keenetic.net", "admin", "pass", "test")
        assert router.base_url == "https://keenetic.net"

    def test_stores_credentials(self):
        router = KeeneticRouter("192.168.1.1", "adminuser", "secret", "my-router")
        assert router.username == "adminuser"
        assert router.password == "secret"
        assert router.name == "my-router"


class TestLogin:
    def test_login_requires_auth_then_succeeds(self):
        router = KeeneticRouter("192.168.1.1", "admin", "pass123", "test")
        with requests_mock.Mocker() as m:
            m.get("http://192.168.1.1/auth", status_code=401,
                  headers={"X-NDM-Realm": "test-realm", "X-NDM-Challenge": "abc123"})
            m.post("http://192.168.1.1/auth", status_code=200)
            assert router.login() is True

    def test_login_already_authenticated(self):
        router = KeeneticRouter("192.168.1.1", "admin", "pass", "test")
        with requests_mock.Mocker() as m:
            m.get("http://192.168.1.1/auth", status_code=200)
            assert router.login() is True

    def test_login_auth_error_returns_false(self):
        router = KeeneticRouter("192.168.1.1", "admin", "pass", "test")
        with requests_mock.Mocker() as m:
            m.get("http://192.168.1.1/auth", status_code=401,
                  headers={"X-NDM-Realm": "r", "X-NDM-Challenge": "c"})
            m.post("http://192.168.1.1/auth", status_code=403)
            assert router.login() is False

    def test_login_connection_error_returns_false(self):
        router = KeeneticRouter("192.168.1.1", "admin", "pass", "test")
        with requests_mock.Mocker() as m:
            m.get("http://192.168.1.1/auth", exc=requests.exceptions.ConnectionError)
            assert router.login() is False

    def test_login_unexpected_status_returns_false(self):
        router = KeeneticRouter("192.168.1.1", "admin", "pass", "test")
        with requests_mock.Mocker() as m:
            m.get("http://192.168.1.1/auth", status_code=500)
            assert router.login() is False


class TestAuthHashComputation:
    def test_md5_hash_is_computed_correctly(self):
        router = KeeneticRouter("192.168.1.1", "user", "secret", "test")
        with requests_mock.Mocker() as m:
            m.get("http://192.168.1.1/auth", status_code=401,
                  headers={"X-NDM-Realm": "test-realm", "X-NDM-Challenge": "test-challenge-123"})
            m.post("http://192.168.1.1/auth", status_code=200)
            router.login()

            body = m.request_history[1].json()
            assert body["login"] == "user"
            assert "password" in body

            import hashlib
            md5_val = hashlib.md5("user:test-realm:secret".encode()).hexdigest()
            expected = hashlib.sha256(f"test-challenge-123{md5_val}".encode()).hexdigest()
            assert body["password"] == expected


class TestKeenRequest:
    def test_get_request(self):
        router = KeeneticRouter("192.168.1.1", "admin", "pass", "test")
        with requests_mock.Mocker() as m:
            m.get(requests_mock.ANY, status_code=200, json={"data": "ok"})
            resp = router.keen_request("test/endpoint")
            assert resp is not None
            assert resp.json() == {"data": "ok"}

    def test_post_request(self):
        router = KeeneticRouter("192.168.1.1", "admin", "pass", "test")
        with requests_mock.Mocker() as m:
            m.post(requests_mock.ANY, status_code=200, json={"result": True})
            resp = router.keen_request("test/endpoint", data={"key": "val"})
            assert resp.json() == {"result": True}

    def test_request_error_returns_none(self):
        router = KeeneticRouter("192.168.1.1", "admin", "pass", "test")
        with requests_mock.Mocker() as m:
            m.get(requests_mock.ANY, exc=requests.exceptions.Timeout)
            resp = router.keen_request("test")
            assert resp is None

    def test_post_request_error_returns_none(self):
        router = KeeneticRouter("192.168.1.1", "admin", "pass", "test")
        with requests_mock.Mocker() as m:
            m.post(requests_mock.ANY, exc=requests.exceptions.Timeout)
            resp = router.keen_request("test", data={"key": "val"})
            assert resp is None

    def test_url_construction(self):
        router = KeeneticRouter("192.168.1.1", "admin", "pass", "test")
        with requests_mock.Mocker() as m:
            m.get("http://192.168.1.1/rci/test/endpoint", status_code=200)
            router.keen_request("rci/test/endpoint")
            assert m.request_history[0].url == "http://192.168.1.1/rci/test/endpoint"


# We can't easily test methods that call login() because login() uses gettext.
# Instead, test login() separately (above) and test URL construction for endpoints.
class TestEndpointURLs:
    def test_keen_request_uses_base_url(self):
        router = KeeneticRouter("10.0.0.1", "admin", "pass", "test")
        with requests_mock.Mocker() as m:
            m.get("http://10.0.0.1/rci/test/ep", status_code=200)
            router.keen_request("rci/test/ep")
            assert len(m.request_history) == 1

    def test_keen_request_post_data(self):
        router = KeeneticRouter("192.168.1.1", "admin", "pass", "test")
        with requests_mock.Mocker() as m:
            m.post("http://192.168.1.1/rci/ip/hotspot/host", status_code=200,
                   json={"status": "ok"})
            data = {"mac": "aa:bb:cc:dd:ee:01", "policy": "block"}
            resp = router.keen_request("rci/ip/hotspot/host", data=data)
            assert resp.json()["status"] == "ok"
            assert m.request_history[-1].json() == data
