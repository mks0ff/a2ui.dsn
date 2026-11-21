import argparse
import calendar
import json
from datetime import date, timedelta
from decimal import Decimal

from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from .config import Settings


def shift_month(value: date, offset: int) -> date:
    index = value.year * 12 + value.month - 1 + offset
    return date(index // 12, index % 12 + 1, 1)


def generate(latest: date) -> dict[str, list[dict]]:
    if latest.day != 1:
        raise ValueError("The latest reference month must start on day 1.")
    first = shift_month(latest, -23)
    data: dict[str, list[dict]] = {
        "establishments": [
            {
                "establishment_id": f"SYN-EST-{i:02}",
                "employer_id": "SYN-EMPLOYER-01",
                "label": f"Etablissement fictif {i}",
            }
            for i in range(1, 4)
        ],
        "employees": [{"employee_id": f"SYN-PERSON-{i:04}"} for i in range(200)],
        "contracts": [],
        "declarations": [],
        "remuneration": [],
        "employment": [],
    }
    for i in range(200):
        start = shift_month(first, (i % 12) if i >= 150 else -12)
        end = shift_month(first, 8 + i % 15).replace(day=15) if i % 11 == 0 else None
        assignments = [(i % 3 + 1, 1)]
        if i % 17 == 0:
            assignments.append(((i + 1) % 3 + 1, 2))
        if i % 23 == 0:
            assignments.append((i % 3 + 1, 3))
        for establishment, suffix in assignments:
            data["contracts"].append(
                {
                    "contract_id": f"SYN-CONTRACT-{i:04}-{suffix}",
                    "employee_id": f"SYN-PERSON-{i:04}",
                    "establishment_id": f"SYN-EST-{establishment:02}",
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat() if end else None,
                }
            )
    for offset in range(24):
        month = shift_month(first, offset)
        last_day = month.replace(day=calendar.monthrange(month.year, month.month)[1])
        for establishment in data["establishments"]:
            est = establishment["establishment_id"]
            versions = (1, 2) if offset in (6, 18) else (1,)
            for version in versions:
                declaration_id = f"SYN-DECL-{est}-{month:%Y%m}-{version}"
                data["declarations"].append(
                    {
                        "declaration_id": declaration_id,
                        "establishment_id": est,
                        "reporting_month": month.isoformat(),
                        "version": version,
                        "accepted": True,
                        "submitted_at": f"{shift_month(month, 1):%Y-%m}-0{version + 4}T12:00:00Z",
                    }
                )
                active = [
                    c
                    for c in data["contracts"]
                    if c["establishment_id"] == est
                    and c["start_date"] <= last_day.isoformat()
                    and (c["end_date"] is None or c["end_date"] >= month.isoformat())
                ]
                for position, contract in enumerate(active):
                    data["employment"].append(
                        {
                            "declaration_id": declaration_id,
                            **{
                                key: contract[key]
                                for key in ("contract_id", "employee_id", "start_date", "end_date")
                            },
                        }
                    )
                    person = int(contract["employee_id"].split("-")[-1])
                    amount = Decimal(2400 + person % 30 * 75 + offset * 8)
                    if contract["contract_id"].endswith(("-2", "-3")):
                        amount /= 4
                    worked_start = max(date.fromisoformat(contract["start_date"]), month)
                    worked_end = min(
                        date.fromisoformat(contract["end_date"])
                        if contract["end_date"]
                        else last_day,
                        last_day,
                    )
                    amount *= Decimal((worked_end - worked_start).days + 1) / last_day.day
                    if version == 2 and position == 0:
                        amount += 125
                    data["remuneration"].append(
                        pay_record(declaration_id, contract, month, amount, "regular")
                    )
                    if offset in (9, 20) and position == 0:
                        data["remuneration"].append(
                            pay_record(
                                declaration_id,
                                contract,
                                shift_month(month, -2),
                                Decimal("150.00"),
                                "adjustment",
                            )
                        )
    return data


def pay_record(
    declaration_id: str, contract: dict, month: date, amount: Decimal, kind: str
) -> dict:
    return {
        "declaration_id": declaration_id,
        "contract_id": contract["contract_id"],
        "employee_id": contract["employee_id"],
        "reference_month": month.isoformat(),
        "kind": kind,
        "gross": str(amount.quantize(Decimal("0.01"))),
        "employee_contributions": str((amount * Decimal("0.22")).quantize(Decimal("0.01"))),
        "employer_contributions": str((amount * Decimal("0.42")).quantize(Decimal("0.01"))),
    }


def reporting_sql(raw_dataset: str) -> dict[str, str]:
    latest = f"""
        SELECT * FROM `{raw_dataset}.declarations`
        WHERE accepted
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY establishment_id, reporting_month
            ORDER BY version DESC, submitted_at DESC
        ) = 1
    """
    return {
        "reporting_payroll": f"""
            WITH current_declarations AS ({latest})
            SELECT r.reference_month AS month, d.establishment_id,
                   r.employee_id, r.contract_id, r.gross, r.kind
            FROM `{raw_dataset}.remuneration` r
            JOIN current_declarations d USING (declaration_id)
        """,
        "reporting_contributions": f"""
            WITH current_declarations AS ({latest})
            SELECT r.reference_month AS month, d.establishment_id,
                   r.employee_id, r.contract_id,
                   r.employee_contributions, r.employer_contributions,
                   r.employee_contributions + r.employer_contributions AS total_contributions
            FROM `{raw_dataset}.remuneration` r
            JOIN current_declarations d USING (declaration_id)
        """,
        "reporting_employment": f"""
            WITH current_declarations AS ({latest})
            SELECT d.reporting_month AS month, d.establishment_id,
                   e.employee_id, e.contract_id
            FROM `{raw_dataset}.employment` e
            JOIN current_declarations d USING (declaration_id)
            WHERE e.start_date <= LAST_DAY(d.reporting_month)
              AND (e.end_date IS NULL OR e.end_date >= LAST_DAY(d.reporting_month))
        """,
    }


SCHEMAS = {
    "establishments": [
        ("establishment_id", "STRING"),
        ("employer_id", "STRING"),
        ("label", "STRING"),
    ],
    "employees": [("employee_id", "STRING")],
    "contracts": [
        ("contract_id", "STRING"),
        ("employee_id", "STRING"),
        ("establishment_id", "STRING"),
        ("start_date", "DATE"),
        ("end_date", "DATE"),
    ],
    "declarations": [
        ("declaration_id", "STRING"),
        ("establishment_id", "STRING"),
        ("reporting_month", "DATE"),
        ("version", "INTEGER"),
        ("accepted", "BOOLEAN"),
        ("submitted_at", "TIMESTAMP"),
    ],
    "employment": [
        ("declaration_id", "STRING"),
        ("contract_id", "STRING"),
        ("employee_id", "STRING"),
        ("start_date", "DATE"),
        ("end_date", "DATE"),
    ],
    "remuneration": [
        ("declaration_id", "STRING"),
        ("contract_id", "STRING"),
        ("employee_id", "STRING"),
        ("reference_month", "DATE"),
        ("kind", "STRING"),
        ("gross", "NUMERIC"),
        ("employee_contributions", "NUMERIC"),
        ("employer_contributions", "NUMERIC"),
    ],
}


def seed(settings: Settings, latest: date) -> None:
    if latest.day != 1:
        raise ValueError("The latest reference month must start on day 1.")
    if not settings.project_id or not settings.bigquery_location:
        raise ValueError("Configure DSN_PROJECT_ID and DSN_BIGQUERY_LOCATION.")
    if latest >= date.today().replace(day=1):
        raise ValueError("Only complete past months can be seeded.")
    client = bigquery.Client(project=settings.project_id, location=settings.bigquery_location)
    raw = f"{settings.dataset}_raw"
    # Refuse both existing datasets before making any change. Never overwrite or reseed.
    for dataset_id in (settings.dataset, raw):
        try:
            client.get_dataset(dataset_id)
        except NotFound:
            continue
        raise ValueError(f"Dataset {dataset_id} already exists. Choose a new DSN_DATASET_ID.")
    for dataset_id in (settings.dataset, raw):
        dataset = bigquery.Dataset(dataset_id)
        dataset.location = settings.bigquery_location
        dataset.description = "Fictional DSN-inspired demo only. Not statutory payroll data."
        client.create_dataset(dataset)
    for name, rows in generate(latest).items():
        schema = [bigquery.SchemaField(key, kind) for key, kind in SCHEMAS[name]]
        client.load_table_from_json(
            rows,
            f"{raw}.{name}",
            job_config=bigquery.LoadJobConfig(schema=schema, write_disposition="WRITE_EMPTY"),
        ).result()
    access = []
    for name, sql in reporting_sql(raw).items():
        table = bigquery.Table(f"{settings.dataset}.{name}")
        table.view_query = sql
        table.labels = {
            "dsn_first_month": shift_month(latest, -23).isoformat(),
            "dsn_latest_month": latest.isoformat(),
        }
        table.description = (
            "Synthetic current-corrected DSN reporting view. "
            "month is reference month; headcount must COUNT(DISTINCT employee_id)."
        )
        client.create_table(table)
        access.append(
            bigquery.AccessEntry(
                None,
                "view",
                {
                    "projectId": settings.project_id,
                    "datasetId": settings.dataset_id,
                    "tableId": name,
                },
            )
        )
    dataset = client.get_dataset(raw)
    dataset.access_entries = [*dataset.access_entries, *access]
    client.update_dataset(dataset, ["access_entries"])
    print(
        json.dumps(
            {
                "dataset": settings.dataset,
                "raw_dataset": raw,
                "first_month": shift_month(latest, -23).isoformat(),
                "latest_month": latest.isoformat(),
                "runtime_access": "Grant dataViewer on reporting views only, plus project jobUser.",
            },
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Explicitly create a new fictional DSN dataset.")
    parser.add_argument(
        "--confirm-create",
        action="store_true",
        required=True,
        help="Acknowledge cloud resource creation and billable load/query storage.",
    )
    parser.add_argument(
        "--latest-month",
        type=date.fromisoformat,
        default=(date.today().replace(day=1) - timedelta(days=1)).replace(day=1),
    )
    args = parser.parse_args()
    seed(Settings(), args.latest_month)


if __name__ == "__main__":
    main()
