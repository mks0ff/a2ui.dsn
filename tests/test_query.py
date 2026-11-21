from unittest.mock import Mock

import pytest
from google.cloud import bigquery

from dsn_agent.config import Settings
from dsn_agent.errors import AnalysisError
from dsn_agent.query import Scope, guarded_sql
from dsn_agent.warehouse import Warehouse

SETTINGS = Settings(project_id="test-project", bigquery_location="EU")
VIEW = "test-project.dsn_demo.reporting_payroll"
SCOPE = Scope("payroll", "2026-01-01", "2026-02-01", ("SYN-EST-01",))


def test_scopes_physical_sources_even_inside_ctes():
    sql, sources = guarded_sql(
        f"WITH payroll AS (SELECT * FROM `{VIEW}`) "
        "SELECT month, SUM(gross) AS brut FROM payroll GROUP BY month",
        SCOPE,
        SETTINGS,
    )
    assert "2026-01-01" in sql and "2026-02-01" in sql
    assert "establishment_id IN ('SYN-EST-01')" in sql
    assert sources == [VIEW]


@pytest.mark.parametrize(
    "sql",
    [
        f"DELETE FROM `{VIEW}` WHERE TRUE",
        f"SELECT * FROM `{VIEW}`; SELECT 1",
        "SELECT * FROM `test-project.dsn_demo_raw.remuneration`",
        "SELECT * FROM `other-project.dsn_demo.reporting_payroll`",
        "SELECT * FROM `test-project.dsn_demo.reporting_payroll*`",
        f"SELECT `other-project.functions.remote`(gross) FROM `{VIEW}`",
        f"SELECT EXTERNAL_QUERY('connection', 'SELECT 1') FROM `{VIEW}`",
        f"SELECT * FROM `{VIEW}` UNION ALL SELECT * FROM `other-project.dataset.secrets`",
        "WITH payroll AS (SELECT * FROM `other-project.dataset.secrets`) SELECT * FROM payroll",
        "SELECT * FROM `test-project.dsn_demo.reporting_employment`",
        "SELECT 42 AS fabricated",
    ],
)
def test_blocks_unapproved_operations_sources_and_functions(sql):
    with pytest.raises(AnalysisError):
        guarded_sql(sql, SCOPE, SETTINGS)


def fake_client(total_rows=1, dry_bytes=500, statement_type="SELECT"):
    client = Mock()
    dry = Mock(total_bytes_processed=dry_bytes, statement_type=statement_type)
    iterator = Mock(total_rows=total_rows)
    iterator.schema = [bigquery.SchemaField("brut", "NUMERIC")]
    iterator.__iter__ = Mock(return_value=iter([{"brut": "123.45"}]))
    job = Mock(job_id="test-job", total_bytes_processed=500)
    job.result.return_value = iterator
    client.query.side_effect = [dry, job]
    return client, job


def test_warehouse_dry_runs_and_enforces_execution_cap_with_job_evidence():
    client, job = fake_client()
    result = Warehouse(SETTINGS, client).execute(
        "owner", f"SELECT SUM(gross) AS brut FROM `{VIEW}`", SCOPE, "Masse salariale"
    )
    assert result.rows == [{"brut": "123.45"}]
    assert result.job_id == "test-job"
    assert client.query.call_args_list[0].kwargs["job_config"].dry_run is True
    assert client.query.call_args_list[1].kwargs["job_config"].maximum_bytes_billed == 104857600
    assert client.query.call_args_list[1].kwargs["job_retry"] is None
    assert job.result.call_args.kwargs["max_results"] == 10001


@pytest.mark.parametrize(
    "dry_bytes,statement_type,code",
    [
        (104857601, "SELECT", "query_cost_limit"),
        (500, "EXPORT_DATA", "blocked_sql"),
        (None, "SELECT", "unknown_cost"),
    ],
)
def test_rejected_dry_run_never_executes(dry_bytes, statement_type, code):
    client, _ = fake_client(dry_bytes=dry_bytes, statement_type=statement_type)
    with pytest.raises(AnalysisError) as error:
        Warehouse(SETTINGS, client).execute("owner", f"SELECT * FROM `{VIEW}`", SCOPE, "Paie")
    assert error.value.code == code
    assert client.query.call_count == 1


def test_oversized_result_rejected_not_silently_truncated():
    client, _ = fake_client(total_rows=10001)
    with pytest.raises(AnalysisError, match="Aucune donnee partielle"):
        Warehouse(SETTINGS, client).execute("owner", f"SELECT * FROM `{VIEW}`", SCOPE, "Paie")


@pytest.mark.parametrize("during_result", [False, True])
def test_query_timeout_reports_error_and_cancels_only_created_jobs(during_result):
    client, job = fake_client()
    if during_result:
        job.result.side_effect = TimeoutError
    else:
        client.query.side_effect = TimeoutError
    with pytest.raises(AnalysisError) as error:
        Warehouse(SETTINGS, client).execute("owner", f"SELECT * FROM `{VIEW}`", SCOPE, "Paie")
    assert error.value.code == "query_timeout"
    assert job.cancel.call_count == int(during_result)
