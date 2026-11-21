import asyncio
from unittest.mock import Mock

import pytest
from google.adk.agents import Agent as RealAgent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.auth.credentials import AnonymousCredentials
from google.cloud import bigquery
from google.genai import types

from dsn_agent.agent import DsnAgent
from dsn_agent.config import Settings
from dsn_agent.errors import AnalysisError
from dsn_agent.results import ResultStore

VIEW = "test-project.dsn_demo.reporting_payroll"
SETTINGS = Settings(
    project_id="test-project",
    bigquery_location="EU",
    vertex_location="europe-west1",
    model="configured-model",
)


class ScriptedModel(BaseLlm):
    model: str = "scripted"
    responses: list[LlmResponse]

    async def generate_content_async(self, llm_request, stream=False):
        assert self.responses, "Unexpected extra model call"
        # Exercising the real ADK runner also validates all tool declarations.
        yield self.responses.pop(0)


def call(name, **args):
    return LlmResponse(
        content=types.Content(
            role="model", parts=[types.Part(function_call=types.FunctionCall(name=name, args=args))]
        )
    )


def finish():
    return LlmResponse(
        content=types.Content(
            role="model", parts=[types.Part(text="Invented value 999999 must not reach the user.")]
        )
    )


def runtime(monkeypatch, responses):
    client = Mock()
    client.get_table.return_value = Mock(
        labels={
            "dsn_first_month": "2024-11-01",
            "dsn_latest_month": "2026-10-01",
        }
    )
    iterator = Mock(total_rows=1)
    iterator.schema = [bigquery.SchemaField("brut", "NUMERIC")]
    iterator.__iter__ = Mock(side_effect=lambda: iter([{"brut": "123.45"}]))
    job = Mock(job_id="real-runner-job", total_bytes_processed=500)
    job.result.return_value = iterator
    dry = Mock(total_bytes_processed=500, statement_type="SELECT")
    client.query.side_effect = lambda *args, **kwargs: dry if kwargs["job_config"].dry_run else job
    monkeypatch.setattr(
        "dsn_agent.agent.google.auth.default",
        lambda **kwargs: (AnonymousCredentials(), "test-project"),
    )
    monkeypatch.setattr("dsn_agent.agent.bigquery.Client", lambda **kwargs: client)
    model = ScriptedModel(responses=responses)
    monkeypatch.setattr(
        "dsn_agent.agent.Agent", lambda **kwargs: RealAgent(**{**kwargs, "model": model})
    )
    return DsnAgent(SETTINGS, ResultStore()), client, model


def test_real_adk_runner_executes_python_tool_and_inherits_context(monkeypatch):
    async def scenario():
        agent, client, model = runtime(
            monkeypatch,
            [
                call(
                    "execute_sql",
                    query=f"SELECT SUM(gross) AS brut FROM `{VIEW}`",
                    metric="payroll",
                    period_kind="trend",
                    establishment_ids=["SYN-EST-02"],
                ),
                finish(),
                call("execute_sql", query=f"SELECT SUM(gross) AS brut FROM `{VIEW}`", metric=""),
                finish(),
            ],
        )
        first, text = await agent.analyze(
            "owner", "Paie sur douze mois pour etablissement 2", "kpi"
        )
        second, _ = await agent.analyze("owner", "Et encore la meme periode ?", "table")
        assert first.result.scope.start_month == "2025-11-01"
        assert first.result.scope.end_month == "2026-10-01"
        assert first.result.scope == second.result.scope
        assert first.result.scope.establishment_ids == ("SYN-EST-02",)
        assert "999999" not in text
        assert first.result.rows == [{"brut": "123.45"}]
        assert first.result.job_id == "real-runner-job"
        assert client.query.call_count == 4  # One dry run and one actual execution per turn.
        assert not model.responses

    asyncio.run(scenario())


def test_two_attempt_budget_includes_rejected_sql_and_never_touches_cloud(monkeypatch):
    async def scenario():
        bad_query = "SELECT * FROM `other-project.secret.payroll`"
        agent, client, _ = runtime(
            monkeypatch,
            [
                call("execute_sql", query=bad_query, metric="payroll"),
                call("execute_sql", query=bad_query, metric="payroll"),
                call("execute_sql", query=f"SELECT SUM(gross) FROM `{VIEW}`", metric="payroll"),
                finish(),
            ],
        )
        with pytest.raises(AnalysisError, match="Source non autorisee"):
            await agent.analyze("owner", "Lisez des donnees", "auto")
        client.query.assert_not_called()
        assert not agent.store.results

    asyncio.run(scenario())


def test_clarification_has_no_query_and_no_fabricated_data(monkeypatch):
    async def scenario():
        agent, client, _ = runtime(
            monkeypatch,
            [
                call(
                    "ask_clarification",
                    question="Souhaitez-vous la masse salariale ou les effectifs ?",
                ),
                finish(),
            ],
        )
        turn, text = await agent.analyze("owner", "Combien ?", "auto")
        assert turn.result is None
        assert text.startswith("Souhaitez-vous")
        client.query.assert_not_called()

    asyncio.run(scenario())


def test_parallel_tool_calls_cannot_execute_multiple_successful_analyses(monkeypatch):
    async def scenario():
        request = call(
            "execute_sql", query=f"SELECT SUM(gross) AS brut FROM `{VIEW}`", metric="payroll"
        )
        request.content.parts *= 2
        agent, client, _ = runtime(monkeypatch, [request, finish()])
        turn, _ = await agent.analyze("owner", "Masse salariale", "kpi")
        assert turn.result is not None
        assert client.query.call_count == 2
        assert len(agent.store.results) == 1

    asyncio.run(scenario())
