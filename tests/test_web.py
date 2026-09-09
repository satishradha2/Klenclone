from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from klen_clone.db import Base, make_engine
from klen_clone.models import SourceSnapshot
from klen_clone.web import create_app


def test_control_center_is_read_only_and_reports_health(tmp_path):
    url = f"sqlite:///{tmp_path / 'web.db'}"
    engine = make_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(SourceSnapshot(name="test-snapshot", source_url="https://example.invalid", is_atomic=False))
        session.commit()
    client = TestClient(create_app(url, "test-snapshot"))
    health = client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["posting_enabled"] is False
    assert health.headers["x-frame-options"] == "DENY"
    rejected = client.post("/api/v1/summary", json={})
    assert rejected.status_code == 405
    assert "mutating methods are disabled" in rejected.json()["detail"]
    protected = client.get("/api/v1/secure/parties")
    assert protected.status_code == 503
    assert protected.json()["detail"] == "Target authentication is not activated"


def test_summary_does_not_expose_confidential_rows(tmp_path):
    url = f"sqlite:///{tmp_path / 'summary.db'}"
    engine = make_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(SourceSnapshot(name="test-snapshot", source_url="https://example.invalid", is_atomic=False))
        session.commit()
    response = TestClient(create_app(url, "test-snapshot")).get("/api/v1/summary")
    assert response.status_code == 200
    assert response.json()["raw_records"] == 0
    assert response.json()["organization_name"] == "ERP Migration Assurance"
    assert "users" not in response.json()


def test_module_workspaces_are_aggregate_only(tmp_path):
    url = f"sqlite:///{tmp_path / 'modules.db'}"
    engine = make_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(SourceSnapshot(name="test-snapshot", source_url="https://example.invalid", is_atomic=False))
        session.commit()
    client = TestClient(create_app(url, "test-snapshot"))
    for module in ("sales", "purchasing", "inventory", "accounting", "crm", "delivery", "reports"):
        response = client.get(f"/api/v1/modules/{module}")
        assert response.status_code == 200
        payload = response.json()
        assert payload["mode"] == "aggregate_read_only"
        assert payload["operational_enabled"] is False
        assert payload["posting_enabled"] is False
        assert payload["confidential_rows_exposed"] is False
        assert len(payload["cards"]) == 6
        assert "items" not in payload
    assert client.get("/api/v1/modules/hrm").status_code == 404
