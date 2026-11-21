# DSN atelier

A local, French-first analytics application over **fictional DSN-inspired data**.
The agent uses the **Google ADK Python SDK**, Gemini through Vertex AI, and
guarded BigQuery Python tools. The React client renders query-backed cards using
the **A2UI Python agent SDK**, A2UI React renderer, and ECharts.

This is descriptive analytics, not payroll advice, compliance validation, or
an official DSN parser. See [the agreed design](docs\DESIGN.md) and
[business definitions](GLOSSARY.md).

## Local setup (Windows PowerShell)

Requirements: Python 3.12+, Node.js 22.12+, npm, and access to a Google Cloud
project with BigQuery and Vertex AI enabled. Run commands from this folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
Set-Location frontend
npm ci
npm run build
Set-Location ..
```

Edit `.env` with your actual values:

| Variable | Meaning |
|---|---|
| `DSN_PROJECT_ID` | Project for query jobs, demo datasets, and Vertex AI |
| `DSN_DATASET_ID` | New reporting dataset name; default `dsn_demo` |
| `DSN_BIGQUERY_LOCATION` | BigQuery dataset/job location |
| `DSN_VERTEX_LOCATION` | Location in which your chosen model is available |
| `DSN_MODEL` | An available Gemini model ID or Vertex model resource name |

No project, region, or model is silently invented. The UI can open without these
values, but analysis stays disabled with a configuration notice.
Never put credentials, employee data, or service-account keys in the frontend.

Authenticate **server-side** using Application Default Credentials. For local
development with the Google Cloud CLI installed:

```powershell
gcloud auth application-default login
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
```

Use your organization's approved ADC/impersonation flow when required.
`gcloud auth login` alone does not establish application-default credentials.

## Explicitly create the synthetic warehouse

Use a **separate setup identity** with dataset/table creation, load/query job,
and dataset-access-update permissions. Configure `DSN_PROJECT_ID`,
`DSN_DATASET_ID`, and `DSN_BIGQUERY_LOCATION` in `.env`, and authenticate with
ADC as described above. Vertex AI settings are not required for seeding.

From the project folder, run the existing Python module:

```powershell
.\.venv\Scripts\python.exe -m dsn_agent.seed --confirm-create
```

The installed `.\.venv\Scripts\dsn-seed.exe --confirm-create` command is
equivalent. Both explicitly create cloud resources and can incur costs;
application startup never runs the seed.

The default period is the latest 24 complete calendar months. An optional
`--latest-month 2026-10-01` selects a complete historical end month:

```powershell
.\.venv\Scripts\python.exe -m dsn_agent.seed --confirm-create --latest-month 2026-10-01
```

To call the seed from your own Python script instead:

```python
from datetime import date

from dsn_agent.config import Settings
from dsn_agent.seed import seed

if __name__ == "__main__":
    # Explicit cloud creation; Settings reads the project's .env file.
    seed(settings=Settings(), latest=date(2026, 10, 1))
```

Run your script with `.\.venv\Scripts\python.exe .\your_script.py`.
The direct function call does not use a `--confirm-create` flag: calling
`seed()` itself performs creation. The same ADC and setup permissions apply.
The end month must be the first day of a complete past month.

The deterministic fixture contains 200 fictional people, three establishments,
multiple contracts, cross-establishment assignments, hires, mid-month departures,
replacement declarations, and remuneration adjustments.

Setup creates `DSN_DATASET_ID` and `DSN_DATASET_ID_raw`. It **refuses an existing
dataset** rather than replacing it. On a partial setup failure, review the
reported cloud error and use a new dedicated dataset name; there is no automatic
destructive cleanup or reseeding.

The three authorized reporting views are:

| View | Columns |
|---|---|
| `reporting_payroll` | `month`, `establishment_id`, `employee_id`, `contract_id`, `gross`, `kind` |
| `reporting_contributions` | `month`, `establishment_id`, `employee_id`, `contract_id`, `employee_contributions`, `employer_contributions`, `total_contributions` |
| `reporting_employment` | `month`, `establishment_id`, `employee_id`, `contract_id` |

`month` is the reference month. Views select the latest **accepted** declaration
per establishment/reporting month before joining facts. Adjustments contribute
to their original reference month. Employment includes only contracts active on
the last day of the month; use `COUNT(DISTINCT employee_id)`, not contract counts
or sums of establishment headcounts.

Before running the app, switch ADC to a **runtime identity** with:

- `roles/bigquery.jobUser` on the compute project.
- `roles/bigquery.dataViewer` on the three reporting **views only**.
- Vertex AI model invocation access, normally `roles/aiplatform.user`.
- Any quota-project/service-usage permissions required by your organization.

Do not grant runtime access to the raw dataset or dataset/table write privileges.
Setup authorizes the reporting views to read the private raw dataset.
Backend SQL validation is defense in depth, not a replacement for IAM.

## Run

After building the frontend:

```powershell
.\.venv\Scripts\python.exe -m uvicorn dsn_agent.api:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**. Bind only to loopback: this demo has local
conversation cookies, not production authentication.

For frontend development, run the Python server above and, in another terminal:

```powershell
Set-Location frontend
npm run dev
```

Open **http://127.0.0.1:5173**; Vite proxies `/api` to Python.
Rebuild and restart Python to serve a changed production frontend.

## Using the application

Select a suggestion to open an editable question and its parameters. Nothing
executes until **Analyser**. Ask follow-up questions to retain the previous
metric, period, and establishments. First snapshots default to the latest
available complete month; first trends use the latest 12 available months.
Every result displays the resolved scope and expandable SQL, sources, job ID,
and processed bytes.

Choose a visualization before execution or use **Afficher en** on a result.
Compatible changes use the same retained result without a model call or new
query. The complete table is always available through pagination.
Incompatible choices explain the restriction instead of aggregating silently.

For establishment comparisons, click a chart bar or an establishment ID in the
table to prepare an **editable follow-up**. Charts also offer keyboard-accessible
**Explorer SYN-EST-...** buttons. The draft asks for that establishment's monthly
trend, using the original card's metric and ending month, over up to 12 available
months. It selects **Courbe** and focuses the composer. Review or edit the question,
then click **Analyser** to run a new guarded query and append another card.
Clicking a result never runs SQL automatically; the original card is retained.
Only recognized establishment IDs actually present in result rows are interactive.

Default configurable limits:

| Boundary | Limit |
|---|---|
| Query billing | 100 MiB per query, checked by dry run and execution maximum |
| Complete results | 10,000 rows |
| Charts | 5,000 plotted points, counting all series |
| SQL attempts | At most two per user message, including rejected proposals |

A 3,000-point chart displays all 3,000 points; exactly 5,000 points is supported.
Above the chart limit, the table remains available and an explicit new filter
or aggregation is required. Results above the row limit are rejected completely.
The model sees computed ranges, not the full result, and cannot invent the
numerical content of a card. These controls are **not a total cloud spending cap**.

Conversation state and results exist only in the backend process memory.
**Nouvelle conversation** clears the current local conversation, not BigQuery job
history, Vertex AI logs, or other Google Cloud retention.

## Maintaining prompts

Edit `config\prompts.json`, then reload the browser. No React changes or
rebuild are necessary. Entries contain a stable ID, category, label, natural
language template, parameter definitions/defaults, visualization, order, and
enabled flag. Placeholder names must match the unique parameter IDs exactly.
Invalid entries produce an explicit catalog error rather than disappearing.
Templates are ordinary questions, not privileged SQL fragments.

`config\agent_instruction.txt` holds the model's DSN rules.
`config\catalog.json` defines the bounded A2UI 1.0 `DSNResult` component; its ID
must match the registered trusted React implementation.

## Interface theme

The interface follows the [A2UI Playground](https://a2ui.open.bot) layout:
a compact header with a menu, a centered welcome screen, icon-led prompt tiles,
and a rounded composer on a pale neutral background. The menu contains
**Nouvelle conversation** and the synthetic-dataset information. Enter submits
an analysis; Shift+Enter inserts a newline. Suggestions remain editable and
never execute automatically.

Theme tokens live in `frontend\src\style.css`; charts read the same variables.
Result cards use a shadcn/ui-style light treatment: 18px rounded white cards,
soft shadows, rounded table/chart frames, and purple-led charts with rounded
bar tops. Tables retain internal scrolling, sticky headers, and pagination.
This styling uses the existing CSS and ECharts; no theme dependency is required.
This is a visual adaptation, not a CopilotKit runtime or
[playground catalog](https://a2ui.open.bot/catalog.json) integration. The bounded
DSN catalog, Python ADK, BigQuery guardrails, and A2UI 1.0 rendering are unchanged.

## Validation

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check dsn_agent tests
Set-Location frontend
npm test
npm run build
```

Tests exercise the real Python ADK runner with a scripted model, A2UI validation
in Python and React, scope guardrails, billing/result limits, complete pagination,
chart boundaries, and correction/deduplication semantics. Cloud responses are
simulated; **live model, warehouse, IAM, region and quota compatibility must
still be verified with your configured project**. No warehouse is created by
tests.

The built-in ADK BigQuery SQL executor is not exposed because it truncates
results and does not return the required job evidence. ADK's
`BigQueryToolset.get_table_info` supplies restricted schema metadata; a Python
ADK function tool performs validated execution with the official BigQuery SDK.
The Python A2UI agent SDK validates deterministic, result-bound surfaces instead
of trusting model-generated numerical payloads.
