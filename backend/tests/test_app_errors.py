"""Error reports from the iPhone app (mobile/src/lib/errors.ts): stored scrubbed, capped, and shown in /v1/health."""
from fastapi.testclient import TestClient

from paxen import main
from paxen.db import AppError, SessionLocal


def test_an_error_report_is_kept_scrubbed_and_shown_in_health(monkeypatch):
    with TestClient(main.app) as c:
        with SessionLocal() as s:
            s.query(AppError).delete()
            s.commit()
        try:
            r = c.post("/v1/app-errors", json={
                "kind": "card",
                "message": "TypeError: Cannot read property 'p50' of null (me@example.com, 51.58261,-0.01283)",
                "stack": "at CommuteHero (index.bundle:1:2345)\nBearer abcdefabcdefabcdefabcdefabcdefabcdef\n"
                         "https://paxen-production.up.railway.app/v1/dashboard",
                "build": "28", "platform": "ios"})
            assert r.status_code == 204
            assert c.post("/v1/app-errors", json={"kind": "nonsense", "message": "x"}).status_code == 422
            assert c.post("/v1/app-errors", json={"message": ""}).status_code == 422

            h = c.get("/v1/health").json()["app_errors"]
            assert len(h) == 1 and h[0]["kind"] == "card" and h[0]["build"] == "28"
            msg = h[0]["message"]
            assert "Cannot read property 'p50' of null" in msg
            assert "example.com" not in msg and "51.58261" not in msg and "<email>" in msg
            stack = "\n".join(h[0]["stack"])
            assert "CommuteHero" in stack and "abcdef" not in stack and "railway.app" not in stack
            full = c.get("/v1/app-errors").json()
            assert full[0]["stack"].startswith("at CommuteHero")
        finally:
            with SessionLocal() as s:
                s.query(AppError).delete()
                s.commit()


def test_only_the_latest_reports_are_kept(monkeypatch):
    monkeypatch.setattr(main, "APP_ERRORS_KEEP", 3)
    with TestClient(main.app) as c:
        try:
            for i in range(6):
                assert c.post("/v1/app-errors", json={"message": f"Error: number {i}"}).status_code == 204
            with SessionLocal() as s:
                kept = [m for (m,) in s.query(AppError.message).order_by(AppError.id)]
            assert kept == ["Error: number 3", "Error: number 4", "Error: number 5"]
        finally:
            with SessionLocal() as s:
                s.query(AppError).delete()
                s.commit()
