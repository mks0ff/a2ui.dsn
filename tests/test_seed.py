import calendar
import sqlite3
from datetime import date
from unittest.mock import Mock

import pytest
import sqlglot

from dsn_agent.config import Settings
from dsn_agent.seed import SCHEMAS, generate, reporting_sql, seed


@pytest.fixture(scope="module")
def dataset():
    return generate(date(2026, 10, 1))


@pytest.fixture(scope="module")
def database(dataset):
    connection = sqlite3.connect(":memory:")

    def last_day(value):
        parsed = date.fromisoformat(value)
        return parsed.replace(day=calendar.monthrange(parsed.year, parsed.month)[1]).isoformat()

    connection.create_function("LAST_DAY", 1, last_day)
    for name, records in dataset.items():
        keys = [field[0] for field in SCHEMAS[name]]
        types = {"NUMERIC": "REAL", "INTEGER": "INTEGER", "BOOLEAN": "INTEGER"}
        columns = ", ".join(f"{key} {types.get(kind, 'TEXT')}" for key, kind in SCHEMAS[name])
        connection.execute(f"CREATE TABLE {name} ({columns})")
        connection.executemany(
            f"INSERT INTO {name} VALUES ({', '.join('?' for _ in keys)})",
            [[row[key] for key in keys] for row in records],
        )
    for name, query in reporting_sql("raw").items():
        sqlite_query = sqlglot.transpile(query, read="bigquery", write="sqlite")[0]
        sqlite_query = sqlite_query.replace('"raw".', "").replace("raw.", "")
        connection.execute(f"CREATE VIEW {name} AS {sqlite_query}")
    yield connection
    connection.close()


def test_fixture_contains_hires_departures_adjustments_and_replacements(dataset):
    assert len(dataset["employees"]) == 200
    assert len(dataset["establishments"]) == 3
    assert len({d["reporting_month"] for d in dataset["declarations"]}) == 24
    assert any(d["version"] == 2 for d in dataset["declarations"])
    assert any(r["kind"] == "adjustment" for r in dataset["remuneration"])
    assert any(c["end_date"] and c["end_date"].endswith("-15") for c in dataset["contracts"])
    assert any(c["start_date"] >= "2024-11-01" for c in dataset["contracts"])


def test_latest_declarations_replace_rather_than_accumulate(database):
    corrected = database.execute("""
        SELECT SUM(gross) FROM remuneration r
        JOIN declarations d USING (declaration_id)
        WHERE d.reporting_month = '2025-05-01' AND d.version = 2
    """).fetchone()[0]
    actual = database.execute(
        "SELECT SUM(gross) FROM reporting_payroll WHERE month='2025-05-01'"
    ).fetchone()[0]
    naive = database.execute("""
        SELECT SUM(gross) FROM remuneration r JOIN declarations d USING (declaration_id)
        WHERE d.reporting_month='2025-05-01'
    """).fetchone()[0]
    assert actual == pytest.approx(corrected)
    assert naive > actual


def test_adjustment_uses_reference_month_and_contributions_are_separate(database):
    naive = database.execute("""
        SELECT SUM(r.gross) FROM remuneration r JOIN declarations d USING (declaration_id)
        WHERE d.reporting_month='2025-08-01'
    """).fetchone()[0]
    actual = database.execute(
        "SELECT SUM(gross) FROM reporting_payroll WHERE month='2025-08-01'"
    ).fetchone()[0]
    assert naive - actual == pytest.approx(450)
    employee, employer, combined = database.execute("""
        SELECT SUM(employee_contributions), SUM(employer_contributions), SUM(total_contributions)
        FROM reporting_contributions WHERE month='2025-08-01'
    """).fetchone()
    assert combined == pytest.approx(employee + employer)
    assert employer > employee


def test_month_end_headcount_deduplicates_contracts_and_establishments(database):
    month = "2024-11-01"
    distinct, contracts = database.execute(
        """
        SELECT COUNT(DISTINCT employee_id), COUNT(*) FROM reporting_employment WHERE month=?
    """,
        (month,),
    ).fetchone()
    per_establishment = database.execute(
        """
        SELECT COUNT(DISTINCT employee_id) FROM reporting_employment WHERE month=?
        GROUP BY establishment_id
    """,
        (month,),
    ).fetchall()
    assert sum(value[0] for value in per_establishment) > distinct
    assert contracts > distinct
    excluded = database.execute("""
        SELECT COUNT(*) FROM reporting_employment r JOIN contracts c USING (contract_id)
        WHERE c.end_date < DATE(r.month, '+1 month', '-1 day')
    """).fetchone()[0]
    assert excluded == 0


def test_seeding_refuses_existing_dataset_before_writes(monkeypatch):
    client = Mock()
    monkeypatch.setattr("dsn_agent.seed.bigquery.Client", lambda **kwargs: client)
    with pytest.raises(ValueError, match="already exists"):
        seed(Settings(project_id="test-project", bigquery_location="EU"), date(2026, 10, 1))
    client.create_dataset.assert_not_called()
    client.load_table_from_json.assert_not_called()


def test_invalid_seed_month_is_rejected_before_cloud_resources(monkeypatch):
    client = Mock()
    monkeypatch.setattr("dsn_agent.seed.bigquery.Client", client)
    with pytest.raises(ValueError, match="day 1"):
        seed(Settings(project_id="test-project", bigquery_location="EU"), date(2026, 10, 15))
    client.assert_not_called()
