import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from dsn_agent.api import create_app
from dsn_agent.config import Settings
from dsn_agent.presentation import Presenter
from dsn_agent.query import Scope
from dsn_agent.results import Result, json_value


def make_result(count=3000, series=1, owner="owner"):
    return Result(
        owner=owner,
        title="Paie",
        rows=[
            {
                "month": (date(2000, 1, 1) + timedelta(days=i)).isoformat(),
                **{f"brut{s}": str(i + s) for s in range(series)},
            }
            for i in range(count)
        ],
        columns=[{"name": "month", "type": "DATE"}]
        + [{"name": f"brut{s}", "type": "NUMERIC"} for s in range(series)],
        sql="SELECT month, gross FROM reporting_payroll",
        sources=["reporting_payroll"],
        job_id="job-123",
        scope=Scope("payroll", "2026-01-01", "2026-01-01"),
    )


@pytest.mark.parametrize("count,selected", [(3000, "line"), (5000, "line"), (5001, "table")])
def test_chart_boundary_and_complete_rows(count, selected):
    result = make_result(count)
    presentation = Presenter().render(result, "line", 5000)
    card = presentation["card"]
    assert card["visualization"] == selected
    assert card["row_count"] == count
    assert len(result.rows) == count
    assert len(card["rows"]) == (count if selected == "line" else 50)
    if count > 5000:
        assert "agregation" in card["notice"]
    assert presentation["messages"][0]["version"] == "1.0"


def test_point_cap_counts_all_series_and_kpi_never_aggregates():
    result = make_result(3000, series=2)
    assert result.presentation("bar", 5000)["visualization"] == "table"
    assert result.presentation("kpi", 5000)["visualization"] == "table"
    assert "agregation implicite" in result.presentation("kpi", 5000)["notice"]


def test_kpi_and_empty_results():
    result = make_result(1)
    assert result.presentation("kpi", 5000)["visualization"] == "kpi"
    assert make_result(0).presentation("auto", 5000)["visualization"] == "table"
    result.rows[0]["brut0"] = None
    assert result.presentation("kpi", 5000)["visualization"] == "table"


def test_duplicate_labels_cannot_be_silently_combined():
    result = make_result(2)
    result.rows[1]["month"] = result.rows[0]["month"]
    assert result.presentation("line", 5000)["visualization"] == "table"


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_non_finite_values_remain_visible_in_table_instead_of_becoming_missing(value):
    result = make_result(1)
    result.rows[0]["brut0"] = json_value(value)
    card = Presenter().render(result, "kpi", 5000)["card"]
    assert card["visualization"] == "table"
    assert card["rows"][0]["brut0"] is not None
    assert card["summary"]["numeric_ranges"]["brut0"]["non_finite_count"] == 1
    assert "representables" in card["notice"]


def test_complete_pagination_switching_and_session_isolation_without_agent_calls():
    app = create_app(Settings())
    with TestClient(app) as client:
        client.post("/api/session")
        owner = client.cookies.get("dsn_session")
        result = make_result(owner=owner)
        app.state.store.add(result)
        all_rows = []
        for offset in range(0, 3000, 200):
            page = client.get(f"/api/results/{result.id}/rows?offset={offset}&limit=200")
            assert page.status_code == 200
            all_rows.extend(page.json()["rows"])
        assert all_rows == result.rows
        original = client.get(f"/api/results/{result.id}?visualization=line").json()["card"]
        changed = client.get(f"/api/results/{result.id}?visualization=bar").json()["card"]
        assert original["evidence"] == changed["evidence"]
        assert original["rows"] == changed["rows"] == result.rows
        assert app.state.runtime is None
        bad = client.get(f"/api/results/{result.id}?visualization=kpi").json()["card"]
        assert bad["visualization"] == "table"
        assert len(bad["rows"]) == 50
        client.cookies.clear()
        client.post("/api/session")
        assert client.get(f"/api/results/{result.id}").status_code == 404


def test_explicit_config_error_and_state_clearing():
    app = create_app(Settings(project_id="", model="", vertex_location="", bigquery_location=""))
    with TestClient(app) as client:
        client.post("/api/session")
        result = make_result(1, owner=client.cookies.get("dsn_session"))
        app.state.store.add(result)
        response = client.post("/api/analyze", json={"question": "Paie ?"})
        assert response.status_code == 503
        assert response.json()["code"] == "not_configured"
        assert client.delete("/api/session").status_code == 200
        assert not app.state.store.results
        assert client.get(f"/api/results/{result.id}").status_code == 401


def test_prompt_catalog_is_hot_reloaded_and_invalid_configuration_is_visible(tmp_path):
    path = tmp_path / "prompts.json"
    entry = {
        "id": "test",
        "label": "Premier",
        "template": "Paie pour {periode}",
        "parameters": [{"id": "periode", "label": "Periode", "default": "2026"}],
        "category": "Paie",
        "visualization": "line",
        "order": 1,
    }
    path.write_text(json.dumps([entry]))
    with TestClient(create_app(Settings(prompt_file=path))) as client:
        assert client.get("/api/prompts").json()[0]["label"] == "Premier"
        entry["label"] = "Mis a jour"
        path.write_text(json.dumps([entry]))
        assert client.get("/api/prompts").json()[0]["label"] == "Mis a jour"
        entry["template"] = "Paie pour {inconnu}"
        path.write_text(json.dumps([entry]))
        error = client.get("/api/prompts")
        assert error.status_code == 500
        assert error.json()["code"] == "prompt_config_error"


def test_rejects_nonlocal_write_origin():
    with TestClient(create_app(Settings())) as client:
        response = client.post("/api/session", headers={"origin": "https://unrelated.example"})
        assert response.status_code == 403


def test_hosted_origin_secure_session_and_result_access():
    origin = "https://dsn-example.run.app"
    settings = Settings(public_origin=origin, _env_file=None)
    with TestClient(create_app(settings), base_url=origin) as client:
        response = client.post("/api/session", headers={"origin": origin})
        assert response.status_code == 200
        cookie = response.headers["set-cookie"]
        assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie
        result = make_result(1, owner=client.cookies.get("dsn_session"))
        client.app.state.store.add(result)
        assert client.get(f"/api/results/{result.id}").status_code == 200
        assert client.delete("/api/session", headers={"origin": origin}).status_code == 200
        assert client.get(f"/api/results/{result.id}").status_code == 401


@pytest.mark.parametrize(
    "origin", ["https://unrelated.run.app", "https://dsn-example.run.app.unrelated.example"]
)
def test_hosted_service_rejects_other_origins_and_hosts(origin):
    app = create_app(Settings(public_origin="https://dsn-example.run.app", _env_file=None))
    with TestClient(app, base_url="https://dsn-example.run.app") as client:
        assert client.post("/api/session", headers={"origin": origin}).status_code == 403
        response = client.get(
            "/api/health", headers={"host": origin.removeprefix("https://")}
        )
        assert response.status_code == 400


def test_cloud_proxy_origin_and_local_cookie_behavior():
    app = create_app(Settings(public_origin="https://dsn-example.run.app", _env_file=None))
    with TestClient(app, base_url="https://dsn-example.run.app") as client:
        assert client.post(
            "/api/session", headers={"origin": "http://localhost:8080"}
        ).status_code == 200
    with TestClient(create_app(Settings(_env_file=None))) as client:
        response = client.post("/api/session", headers={"origin": "http://localhost:8080"})
        assert response.status_code == 200
        assert "Secure" not in response.headers["set-cookie"]


@pytest.mark.parametrize(
    "origin",
    [
        "http://dsn-example.run.app",
        "https://dsn-example.run.app/api",
        "https://user:password@dsn-example.run.app",
        "https://dsn-example.run.app?query=1",
        "https://dsn-example.run.app#fragment",
    ],
)
def test_rejects_invalid_public_origin_configuration(origin):
    with pytest.raises(ValueError, match="HTTPS origin"):
        Settings(public_origin=origin, _env_file=None)
