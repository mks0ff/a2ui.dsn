import asyncio
import json
from dataclasses import dataclass, field
from datetime import date

import google.auth
from google.adk.agents import Agent
from google.adk.agents.run_config import RunConfig
from google.adk.integrations.bigquery import BigQueryCredentialsConfig, BigQueryToolset
from google.adk.integrations.bigquery.config import BigQueryToolConfig, WriteMode
from google.adk.models import Gemini
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import ToolContext
from google.adk.tools.base_tool import BaseTool
from google.cloud import bigquery
from google.genai import types

from .config import ROOT, Settings
from .errors import AnalysisError
from .query import Scope
from .results import Result, ResultStore
from .seed import shift_month
from .warehouse import Warehouse

APP_NAME = "dsn_analytics"
METRICS = {
    "payroll": "Masse salariale brute",
    "headcount": "Effectif en fin de mois",
    "contributions": "Cotisations salariales, patronales et total",
}


@dataclass
class Conversation:
    previous_scope: Scope | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass
class Turn:
    attempts: int = 0
    query_in_progress: bool = False
    result: Result | None = None
    clarification: str | None = None
    errors: list[dict] = field(default_factory=list)


class DsnAgent:
    def __init__(self, settings: Settings, store: ResultStore):
        if settings.missing:
            raise AnalysisError(
                "Configuration manquante : " + ", ".join(settings.missing), "not_configured", 503
            )
        self.settings = settings
        self.store = store
        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        self.credentials = credentials
        self.client = bigquery.Client(
            project=settings.project_id,
            credentials=credentials,
            location=settings.bigquery_location,
        )
        self.warehouse = Warehouse(settings, self.client)
        self.sessions = InMemorySessionService()
        self.conversations: dict[str, Conversation] = {}
        self.availability: tuple[str, str] | None = None
        self.model = Gemini(
            model=settings.model,
            client_kwargs={
                "enterprise": True,
                "project": settings.project_id,
                "location": settings.vertex_location,
                "credentials": credentials,
            },
        )

    def _availability(self) -> tuple[str, str]:
        if self.availability is None:
            table = self.client.get_table(f"{self.settings.dataset}.reporting_payroll")
            labels = table.labels or {}
            first, latest = labels.get("dsn_first_month"), labels.get("dsn_latest_month")
            if not first or not latest:
                raise AnalysisError(
                    "Metadonnees de disponibilite absentes. Utilisez le jeu de demonstration "
                    "cree par dsn-seed.",
                    "dataset_not_ready",
                    503,
                )
            Scope("payroll", first, latest)
            if latest >= date.today().replace(day=1).isoformat():
                raise AnalysisError(
                    "Le dernier mois disponible n'est pas complet.", "dataset_not_ready", 503
                )
            self.availability = first, latest
        return self.availability

    async def clear(self, owner: str) -> None:
        conversation = self.conversations.get(owner)
        if conversation and conversation.lock.locked():
            raise AnalysisError("Une analyse est en cours.", "busy", 409)
        self.conversations.pop(owner, None)
        await self.sessions.delete_session(app_name=APP_NAME, user_id=owner, session_id=owner)
        self.store.clear(owner)

    async def analyze(self, owner: str, question: str, preferred: str) -> tuple[Turn, str]:
        conversation = self.conversations.setdefault(owner, Conversation())
        if conversation.lock.locked():
            raise AnalysisError("Une analyse est deja en cours.", "busy", 409)
        async with conversation.lock:
            first, latest = await asyncio.to_thread(self._availability)
            if not await self.sessions.get_session(
                app_name=APP_NAME, user_id=owner, session_id=owner
            ):
                await self.sessions.create_session(
                    app_name=APP_NAME, user_id=owner, session_id=owner
                )
            turn = Turn()

            async def execute_sql(
                query: str,
                metric: str,
                period_kind: str = "snapshot",
                start_month: str = "",
                end_month: str = "",
                establishment_ids: list[str] | None = None,
            ) -> dict:
                """Execute a read-only DSN SELECT with enforced reference-month/establishment scope.

                Use fully qualified approved reporting views. The backend scopes every source.
                metric: payroll, headcount or contributions.
                period_kind: trend (12 months initially) or snapshot (latest month initially).
                start_month/end_month: YYYY-MM-01, empty to retain previous scope or use defaults.
                establishment_ids: null retains prior scope; [] explicitly selects all establishments.
                Dates are reference months, not payment or submission dates.
                """
                if turn.result is not None:
                    return {
                        "status": "ERROR",
                        "message": "Une analyse a deja abouti pour ce message.",
                    }
                if turn.query_in_progress:
                    return {
                        "status": "ERROR",
                        "message": "Une requete SQL est deja en cours pour ce message.",
                    }
                if turn.attempts >= self.settings.max_sql_attempts:
                    return {"status": "ERROR", "message": "Limite de deux tentatives SQL atteinte."}
                turn.attempts += 1
                turn.query_in_progress = True
                try:
                    previous = conversation.previous_scope
                    if period_kind not in {"snapshot", "trend"}:
                        raise AnalysisError("Type de periode invalide.", "invalid_scope")
                    end = end_month or (previous.end_month if previous else latest)
                    start = start_month or (
                        previous.start_month
                        if previous and not end_month
                        else (
                            max(first, shift_month(date.fromisoformat(end), -11).isoformat())
                            if period_kind == "trend"
                            else end
                        )
                    )
                    scope = Scope(
                        metric=metric or (previous.metric if previous else ""),
                        start_month=start,
                        end_month=end,
                        establishment_ids=tuple(
                            establishment_ids
                            if establishment_ids is not None
                            else (previous.establishment_ids if previous else ())
                        ),
                    )
                    if start < first or end > latest:
                        raise AnalysisError(
                            f"Donnees disponibles du {first} au {latest}.", "invalid_scope"
                        )
                    result = await asyncio.to_thread(
                        self.warehouse.execute, owner, query, scope, METRICS[scope.metric]
                    )
                    self.store.add(result)
                    turn.result = result
                    conversation.previous_scope = scope
                    return {
                        "status": "SUCCESS",
                        "result_id": result.id,
                        "summary": result.summary(),
                        "columns": result.columns,
                        "job_id": result.job_id,
                        "instruction": "Les donnees sont liees a la carte. Ne relancez pas de SQL.",
                    }
                except (AnalysisError, ValueError) as exc:
                    code = exc.code if isinstance(exc, AnalysisError) else "invalid_scope"
                    error = {"status": "ERROR", "code": code, "message": str(exc)}
                    turn.errors.append(error)
                    return error
                finally:
                    turn.query_in_progress = False

            def ask_clarification(question: str) -> dict:
                """Ask a French clarification, or explain an unsupported non-descriptive request."""
                turn.clarification = question
                return {"status": "CLARIFICATION_REQUIRED", "question": question}

            async def before_tool(
                tool: BaseTool, args: dict, tool_context: ToolContext
            ) -> dict | None:
                if tool.name == "get_table_info":
                    project = args.get("project_id") or self.settings.project_id
                    dataset = args.get("dataset_id") or self.settings.dataset_id
                    full_name = f"{project}.{dataset}.{args.get('table_id', '')}"
                    if full_name not in self.settings.approved_views:
                        error = {
                            "status": "ERROR",
                            "code": "blocked_metadata",
                            "message": "Metadonnees hors des vues approuvees interdites.",
                        }
                        turn.errors.append(error)
                        return error
                return None

            toolset = BigQueryToolset(
                tool_filter=["get_table_info"],
                credentials_config=BigQueryCredentialsConfig(credentials=self.credentials),
                bigquery_tool_config=BigQueryToolConfig(
                    write_mode=WriteMode.BLOCKED,
                    maximum_bytes_billed=self.settings.max_bytes_billed,
                    max_query_result_rows=self.settings.max_result_rows + 1,
                    compute_project_id=self.settings.project_id,
                    default_project_id=self.settings.project_id,
                    default_dataset_id=self.settings.dataset_id,
                    location=self.settings.bigquery_location,
                ),
            )
            context = {
                "available_months": [first, latest],
                "previous_scope": (
                    {
                        "metric": conversation.previous_scope.metric,
                        "start_month": conversation.previous_scope.start_month,
                        "end_month": conversation.previous_scope.end_month,
                        "establishment_ids": conversation.previous_scope.establishment_ids,
                    }
                    if conversation.previous_scope
                    else None
                ),
                "approved_views": sorted(self.settings.approved_views),
                "visualization_preference": preferred,
            }
            instruction = (ROOT / "config" / "agent_instruction.txt").read_text(encoding="utf-8")
            agent = Agent(
                name="dsn_agent",
                model=self.model,
                instruction=instruction + "\nRuntime context:\n" + json.dumps(context),
                tools=[toolset, execute_sql, ask_clarification],
                before_tool_callback=before_tool,
                generate_content_config=types.GenerateContentConfig(temperature=0),
            )
            runner = Runner(agent=agent, app_name=APP_NAME, session_service=self.sessions)
            try:
                async for event in runner.run_async(
                    user_id=owner,
                    session_id=owner,
                    new_message=types.Content(role="user", parts=[types.Part(text=question)]),
                    run_config=RunConfig(max_llm_calls=6),
                ):
                    if event.error_code:
                        raise AnalysisError(
                            f"Le modele a interrompu l'analyse : {event.error_message}",
                            "model_error",
                            502,
                        )
            finally:
                await runner.close()
            if turn.result:
                result = turn.result
                scope = result.scope
                establishments = ", ".join(scope.establishment_ids) or "tous les etablissements"
                text = (
                    f"{result.title} : {len(result.rows):,} ligne(s) conservee(s). "
                    f"Periode de reference : {scope.start_month} au {scope.end_month} ; "
                    f"{establishments}."
                )
                if not result.rows:
                    text += " Aucune donnee pour ces filtres."
                return turn, text
            if turn.clarification:
                return turn, turn.clarification
            if turn.errors:
                raise AnalysisError(turn.errors[-1]["message"], turn.errors[-1]["code"])
            raise AnalysisError(
                "Aucune requete executee. Precisez l'indicateur, la periode ou les etablissements.",
                "no_analysis",
            )
