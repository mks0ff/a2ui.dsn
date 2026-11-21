import math
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from .errors import AnalysisError
from .query import Scope

NUMERIC_TYPES = {"INTEGER", "INT64", "FLOAT", "FLOAT64", "NUMERIC", "BIGNUMERIC", "DECIMAL"}
TEMPORAL_TYPES = {"DATE", "DATETIME", "TIMESTAMP"}


def json_value(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


@dataclass
class Result:
    owner: str
    title: str
    rows: list[dict]
    columns: list[dict]
    sql: str
    sources: list[str]
    job_id: str
    scope: Scope
    bytes_processed: int = 0
    id: str = field(default_factory=lambda: str(uuid4()))

    def summary(self) -> dict:
        numeric = [c["name"] for c in self.columns if c["type"] in NUMERIC_TYPES]
        # Headcounts are not additive across establishments or months.
        stats = {}
        for name in numeric:
            values = [Decimal(str(row[name])) for row in self.rows if row.get(name) is not None]
            finite = [value for value in values if value.is_finite()]
            if finite:
                stats[name] = {"min": str(min(finite)), "max": str(max(finite))}
            if len(finite) != len(values):
                stats.setdefault(name, {})["non_finite_count"] = len(values) - len(finite)
        return {"row_count": len(self.rows), "numeric_ranges": stats, "scope": asdict(self.scope)}

    def compatibility(self, point_limit: int) -> tuple[dict, str | None, list[str]]:
        numeric = [c["name"] for c in self.columns if c["type"] in NUMERIC_TYPES]
        dimensions = [c for c in self.columns if c["type"] not in NUMERIC_TYPES]
        x = dimensions[0]["name"] if len(dimensions) == 1 else None
        reason = None
        if len(dimensions) > 1:
            reason = "Plusieurs dimensions : choisissez une analyse avec une seule dimension."
        elif any(
            c["type"] not in TEMPORAL_TYPES | {"STRING", "BOOLEAN", "BOOL"} for c in dimensions
        ):
            reason = "La dimension ne peut pas etre representee sur un graphique."
        elif (
            not numeric
            or not self.rows
            or not any(row.get(name) is not None for row in self.rows for name in numeric)
        ):
            reason = "Aucune valeur numerique exploitable."
        elif any(
            row.get(name) is not None and not math.isfinite(float(row[name]))
            for row in self.rows
            for name in numeric
        ):
            reason = "Certaines valeurs ne sont pas representables sur un graphique."
        elif len(self.rows) * len(numeric) > point_limit:
            reason = (
                f"Ce resultat depasse {point_limit:,} points. "
                "Conservez le tableau ou demandez explicitement une agregation ou un filtre."
            )
        elif x and len({str(row.get(x)) for row in self.rows}) != len(self.rows):
            reason = "Les libelles ne sont pas uniques ; precisez le regroupement souhaite."
        elif x and any(row.get(x) is None for row in self.rows):
            reason = "La dimension contient des valeurs manquantes."
        elif not x and len(self.rows) != 1:
            reason = "Il manque une dimension pour distinguer les lignes."
        kpi_reason = None
        if len(self.rows) != 1 or len(numeric) != 1:
            kpi_reason = "Un KPI exige une ligne et une seule mesure, sans agregation implicite."
        line_reason = reason
        if not line_reason and (not x or dimensions[0]["type"] not in TEMPORAL_TYPES):
            line_reason = "Une courbe exige une dimension temporelle de type DATE."
        return (
            {
                "table": None,
                "bar": reason,
                "line": line_reason,
                "kpi": kpi_reason or reason,
            },
            x,
            numeric,
        )

    def presentation(self, preferred: str, point_limit: int) -> dict:
        options, x, series = self.compatibility(point_limit)
        selected = preferred
        notice = None
        if selected == "auto":
            selected = next(
                kind for kind in ("kpi", "line", "bar", "table") if options[kind] is None
            )
        if options[selected] is not None:
            notice = options[selected]
            selected = "table"
        return {
            "result_id": self.id,
            "title": self.title,
            "visualization": selected,
            "options": options,
            "notice": notice,
            "x": x,
            "series": series,
            "row_count": len(self.rows),
            "columns": self.columns,
            "rows": self.rows if selected != "table" else self.rows[:50],
            "evidence": {
                "sql": self.sql,
                "sources": self.sources,
                "job_id": self.job_id,
                "bytes_processed": self.bytes_processed,
                "scope": asdict(self.scope),
            },
            "summary": self.summary(),
        }


class ResultStore:
    def __init__(self):
        self.results: dict[str, Result] = {}

    def add(self, result: Result) -> None:
        self.results[result.id] = result

    def get(self, owner: str, result_id: str) -> Result:
        result = self.results.get(result_id)
        if result is None or result.owner != owner:
            raise AnalysisError("Resultat introuvable ou expire.", "not_found", 404)
        return result

    def clear(self, owner: str) -> None:
        for key in [key for key, result in self.results.items() if result.owner == owner]:
            del self.results[key]
