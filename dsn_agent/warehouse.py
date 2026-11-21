from google.api_core.exceptions import GoogleAPICallError
from google.cloud import bigquery

from .config import Settings
from .errors import AnalysisError
from .query import Scope, guarded_sql
from .results import Result, json_value


class Warehouse:
    def __init__(self, settings: Settings, client: bigquery.Client):
        self.settings = settings
        self.client = client

    def execute(self, owner: str, query: str, scope: Scope, title: str) -> Result:
        sql, sources = guarded_sql(query, scope, self.settings)
        job = None
        try:
            dry = self.client.query(
                sql,
                location=self.settings.bigquery_location,
                job_config=bigquery.QueryJobConfig(
                    dry_run=True,
                    use_query_cache=False,
                    maximum_bytes_billed=self.settings.max_bytes_billed,
                ),
            )
            if dry.statement_type != "SELECT":
                raise AnalysisError("Seuls les SELECT sont autorises.", "blocked_sql")
            if dry.total_bytes_processed is None:
                raise AnalysisError("Le cout estime de la requete est inconnu.", "unknown_cost")
            if dry.total_bytes_processed > self.settings.max_bytes_billed:
                raise AnalysisError(
                    "La requete depasse la limite configuree de "
                    f"{self.settings.max_bytes_billed / 1024 / 1024:g} MiB.",
                    "query_cost_limit",
                )
            job = self.client.query(
                sql,
                location=self.settings.bigquery_location,
                job_config=bigquery.QueryJobConfig(
                    maximum_bytes_billed=self.settings.max_bytes_billed,
                    labels={"app": "dsn-analytics"},
                ),
                job_retry=None,
            )
            iterator = job.result(max_results=self.settings.max_result_rows + 1, timeout=120)
            if (
                iterator.total_rows is not None
                and iterator.total_rows > self.settings.max_result_rows
            ):
                raise AnalysisError(
                    f"Le resultat depasse {self.settings.max_result_rows:,} lignes. "
                    "Aucune donnee partielle n'est presentee ; precisez un filtre.",
                    "result_limit",
                )
            rows = [json_value(dict(row.items())) for row in iterator]
            if len(rows) > self.settings.max_result_rows:
                raise AnalysisError(
                    "Resultat trop volumineux ; precisez un filtre.", "result_limit"
                )
            return Result(
                owner=owner,
                title=title,
                rows=rows,
                columns=[
                    {"name": column.name, "type": column.field_type} for column in iterator.schema
                ],
                sql=sql,
                sources=sources,
                job_id=job.job_id,
                scope=scope,
                bytes_processed=job.total_bytes_processed or 0,
            )
        except GoogleAPICallError as exc:
            raise AnalysisError(f"BigQuery a refuse la requete : {exc}", "bigquery_error") from exc
        except TimeoutError as exc:
            if job is not None:
                job.cancel()
            raise AnalysisError(
                "Delai BigQuery depasse."
                + (" Annulation du job demandee." if job is not None else ""),
                "query_timeout",
            ) from exc
