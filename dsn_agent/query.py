from dataclasses import dataclass
from datetime import date

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.scope import traverse_scope

from .config import Settings
from .errors import AnalysisError

# No anonymous, remote, ML, table-valued or user-defined functions.
SAFE_FUNCTIONS = {
    "SUM",
    "AVG",
    "COUNT",
    "MIN",
    "MAX",
    "ROUND",
    "ABS",
    "COALESCE",
    "NULLIF",
    "CAST",
    "TRY_CAST",
    "DATE",
    "DATE_TRUNC",
    "LAST_DAY",
    "EXTRACT",
    "TIME_TO_STR",
    "IF",
    "CASE",
    "IFNULL",
    "COUNT_IF",
    "SAFE_DIVIDE",
    "DIV",
    "ROW_NUMBER",
    "LAG",
    "LEAD",
    "RANK",
    "DENSE_RANK",
}


@dataclass(frozen=True)
class Scope:
    metric: str
    start_month: str
    end_month: str
    establishment_ids: tuple[str, ...] = ()

    def __post_init__(self):
        for value in (self.start_month, self.end_month):
            try:
                parsed = date.fromisoformat(value)
            except ValueError as exc:
                raise AnalysisError(
                    "Utilisez des mois au format AAAA-MM-01.", "invalid_scope"
                ) from exc
            if parsed.day != 1 or parsed.isoformat() != value:
                raise AnalysisError("Le mois doit commencer au premier jour.", "invalid_scope")
        if self.start_month > self.end_month:
            raise AnalysisError("La periode de debut depasse la fin.", "invalid_scope")
        if self.metric not in {"payroll", "headcount", "contributions"}:
            raise AnalysisError("Indicateur DSN non pris en charge.", "invalid_scope")
        if not set(self.establishment_ids).issubset({"SYN-EST-01", "SYN-EST-02", "SYN-EST-03"}):
            raise AnalysisError("Etablissement synthetique inconnu.", "invalid_scope")


def guarded_sql(query: str, scope: Scope, settings: Settings) -> tuple[str, list[str]]:
    try:
        statements = sqlglot.parse(query, read="bigquery")
    except SqlglotError as exc:
        raise AnalysisError(f"SQL invalide : {exc}", "blocked_sql") from exc
    if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.Union)):
        raise AnalysisError("Une seule requete SELECT est autorisee.", "blocked_sql")
    tree = statements[0]
    for node in tree.walk():
        if isinstance(node, (exp.Into, exp.Command, exp.DDL, exp.DML)):
            raise AnalysisError("Operation SQL interdite.", "blocked_sql")
        if isinstance(node, exp.Func):
            if isinstance(node, exp.Anonymous) or node.sql_name() not in SAFE_FUNCTIONS:
                raise AnalysisError(f"Fonction non autorisee : {node.sql_name()}.", "blocked_sql")
            if isinstance(node.parent, exp.Dot):
                raise AnalysisError("Les fonctions qualifiees sont interdites.", "blocked_sql")

    tables: dict[int, exp.Table] = {}
    for sql_scope in traverse_scope(tree):
        for source in sql_scope.sources.values():
            if isinstance(source, exp.Table):
                tables[id(source)] = source
    if not tables:
        raise AnalysisError("La requete doit lire une vue DSN approuvee.", "blocked_sql")
    sources = set()
    expected = f"{settings.dataset}.reporting_{ {'payroll': 'payroll', 'headcount': 'employment', 'contributions': 'contributions'}[scope.metric] }"
    for table in tables.values():
        name = f"{table.catalog}.{table.db}.{table.name}"
        if name not in settings.approved_views or not isinstance(table.this, exp.Identifier):
            raise AnalysisError(f"Source non autorisee : {name}.", "blocked_sql")
        if name != expected:
            raise AnalysisError(
                "La source ne correspond pas a l'indicateur annonce.", "blocked_sql"
            )
        if table.args.get("version") or table.args.get("pivots"):
            raise AnalysisError("Les versions historiques et pivots sont interdits.", "blocked_sql")
        sources.add(name)
        conditions = f"month BETWEEN DATE '{scope.start_month}' AND DATE '{scope.end_month}'"
        if scope.establishment_ids:
            ids = ", ".join(f"'{value}'" for value in scope.establishment_ids)
            conditions += f" AND establishment_id IN ({ids})"
        # Scope every physical source, including those nested inside CTEs/subqueries.
        scoped = sqlglot.parse_one(
            f"SELECT * FROM `{name}` WHERE {conditions}", read="bigquery"
        ).subquery(alias=table.alias_or_name)
        table.replace(scoped)
    return tree.sql(dialect="bigquery"), sorted(sources)
