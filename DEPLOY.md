# Deploy DSN atelier to Cloud Run

This runbook deploys **one private, IAM-protected Cloud Run service** containing
the Python ADK/FastAPI backend and the built React/A2UI frontend. Cloud Build
runs the checks, builds the Linux container, smoke-tests it without cloud data,
pushes it to Artifact Registry, and deploys it. Docker and Node.js are not
required on your Windows computer for this path.

These commands create billable resources and change IAM. Review the project,
regions, identities, and organization policies before running them. Deployment
does **not** create or seed BigQuery datasets, make the app public, or upload
your local `.env` or Google credentials.

## 1. Prerequisites and deployment values

Install the [Google Cloud CLI](https://cloud.google.com/sdk/docs/install)
including `gcloud` and `bq`. Use a project with billing enabled. Run the
PowerShell examples from the project root, in order, and stop on any failed
command. PowerShell 5.1 does not automatically stop on a native program's
nonzero exit code; inspect `$LASTEXITCODE` before continuing.

Use the same PowerShell window to retain these variables. Replace every
placeholder; the locations below are examples, not application defaults.
BigQuery location must match the existing dataset, and Vertex location must
support your chosen model and satisfy your data residency requirements.

```powershell
gcloud auth login
gcloud version
bq version

$ProjectId = "YOUR_PROJECT_ID"
$Region = "europe-west1"
$BigQueryLocation = "EU"
$VertexLocation = "europe-west1"
$Model = "REPLACE_WITH_AVAILABLE_GEMINI_MODEL_ID"
$Dataset = "dsn_demo"
$Repository = "dsn-containers"
$Service = "dsn-atelier"
$RuntimeAccount = "dsn-runtime"
$BuildAccount = "dsn-build"
$RuntimeSa = "${RuntimeAccount}@${ProjectId}.iam.gserviceaccount.com"
$BuildSa = "${BuildAccount}@${ProjectId}.iam.gserviceaccount.com"
$BuildSaResource = "projects/${ProjectId}/serviceAccounts/${BuildSa}"
$SourceBucket = "${ProjectId}-dsn-build-source"
$DeployerEmail = "deployer@example.com"
$InvokerEmail = "analyst@example.com"
```

Use a dedicated service name. The pipeline refuses to reuse an existing
service with `allUsers` or `allAuthenticatedUsers` IAM bindings. It manages the
service's environment variables and routes **100% of traffic to the new
revision**, replacing previous traffic splits.

## 2. One-time infrastructure setup

An administrator performs this section. They need permissions to enable APIs,
create service accounts, manage project/service-account IAM, create an Artifact
Registry repository and Storage bucket, and grant access to the reporting
views. Typical setup roles include Service Usage Admin, Service Account Admin,
Project IAM Admin, Artifact Registry Admin, and Storage Admin, plus the
BigQuery permissions needed for the data setup. These are **setup** privileges,
not runtime or analyst privileges.

Enable the APIs:

```powershell
gcloud services enable `
  cloudbuild.googleapis.com `
  run.googleapis.com `
  artifactregistry.googleapis.com `
  cloudresourcemanager.googleapis.com `
  iam.googleapis.com `
  logging.googleapis.com `
  storage.googleapis.com `
  bigquery.googleapis.com `
  aiplatform.googleapis.com `
  --project=$ProjectId
```

Create separate runtime and build identities:

```powershell
gcloud iam service-accounts create $RuntimeAccount `
  --display-name="DSN Cloud Run runtime" --project=$ProjectId

gcloud iam service-accounts create $BuildAccount `
  --display-name="DSN build and deployment" --project=$ProjectId
```

Create the container repository and a private source-staging bucket:

```powershell
gcloud artifacts repositories create $Repository `
  --repository-format=docker --location=$Region --project=$ProjectId

gcloud storage buckets create "gs://${SourceBucket}" `
  --location=$Region --uniform-bucket-level-access `
  --public-access-prevention --project=$ProjectId
```

Creation commands are one-time commands: if a resource exists, inspect it
rather than deleting or recreating it. A bucket name must be globally unique;
change `$SourceBucket` if the chosen name is unavailable.

### Build identity permissions

The build identity can deploy Cloud Run, write build logs, push to this
repository, read uploaded source, and attach **only the runtime identity**.
It does not need BigQuery data access.

```powershell
foreach ($Role in @("roles/run.admin", "roles/logging.logWriter", "roles/serviceusage.serviceUsageConsumer")) {
  gcloud projects add-iam-policy-binding $ProjectId `
    --member="serviceAccount:${BuildSa}" --role=$Role --condition=None
  if ($LASTEXITCODE -ne 0) { throw "Failed to grant $Role to the build identity" }
}

gcloud artifacts repositories add-iam-policy-binding $Repository `
  --location=$Region --project=$ProjectId `
  --member="serviceAccount:${BuildSa}" --role=roles/artifactregistry.writer

gcloud storage buckets add-iam-policy-binding "gs://${SourceBucket}" `
  --member="serviceAccount:${BuildSa}" --role=roles/storage.objectViewer

gcloud iam service-accounts add-iam-policy-binding $RuntimeSa `
  --project=$ProjectId --member="serviceAccount:${BuildSa}" `
  --role=roles/iam.serviceAccountUser
```

Cloud Run Admin is used because this pipeline creates the service and enforces
private IAM access. The same-project Cloud Build and Cloud Run **service
agents** must retain their Google-managed service-agent roles. These agents
are different from `$BuildSa` and `$RuntimeSa`; do not replace them with either.

### Human deployer permissions

The submitting user can create builds, upload source, and select the build
identity. Build and runtime identities never use a downloaded service-account
key.

```powershell
foreach ($Role in @("roles/cloudbuild.builds.editor", "roles/serviceusage.serviceUsageConsumer", "roles/logging.viewer")) {
  gcloud projects add-iam-policy-binding $ProjectId `
    --member="user:${DeployerEmail}" --role=$Role --condition=None
  if ($LASTEXITCODE -ne 0) { throw "Failed to grant $Role to the deployer" }
}

gcloud storage buckets add-iam-policy-binding "gs://${SourceBucket}" `
  --member="user:${DeployerEmail}" --role=roles/storage.objectAdmin

gcloud iam service-accounts add-iam-policy-binding $BuildSa `
  --project=$ProjectId --member="user:${DeployerEmail}" `
  --role=roles/iam.serviceAccountUser
```

Storage Object Admin here is scoped to the dedicated staging bucket, not every
bucket in the project. Build-log access can reveal application/source details;
limit it to maintainers.

## 3. Prepare BigQuery separately

Skip seeding if the documented synthetic reporting views already exist.
Deployment never seeds, truncates, or changes warehouse data.

For a new dataset, use an approved **setup identity**, separate from the runtime
service account. It needs project-level BigQuery dataset creation and query
job permissions, plus table/load/view creation and dataset access-update
permissions on the new datasets. BigQuery User on the project allows dataset
creation and query jobs; the dataset creator receives ownership of its new
datasets. Follow your organization's setup policy if these permissions are
restricted.

Python 3.12+ is needed only for this local seed path:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
gcloud auth application-default login
gcloud auth application-default set-quota-project $ProjectId

$env:DSN_PROJECT_ID = $ProjectId
$env:DSN_DATASET_ID = $Dataset
$env:DSN_BIGQUERY_LOCATION = $BigQueryLocation
.\.venv\Scripts\python.exe -m dsn_agent.seed --confirm-create
```

This explicitly creates `${Dataset}` and `${Dataset}_raw` with 24 complete
months of fictional data. It refuses existing datasets. On a partial failure,
inspect the error and choose a new dedicated dataset name rather than deleting
data automatically. See [README.md](README.md) for historical end-month selection
and data semantics.

Grant the runtime identity project-level query/model permissions:

```powershell
foreach ($Role in @("roles/bigquery.jobUser", "roles/aiplatform.user", "roles/serviceusage.serviceUsageConsumer")) {
  gcloud projects add-iam-policy-binding $ProjectId `
    --member="serviceAccount:${RuntimeSa}" --role=$Role --condition=None
  if ($LASTEXITCODE -ne 0) { throw "Failed to grant $Role to the runtime identity" }
}
```

Grant Data Viewer on the **three individual reporting views**, not the project,
reporting dataset, or raw dataset:

```powershell
foreach ($View in @("reporting_payroll", "reporting_contributions", "reporting_employment")) {
  bq add-iam-policy-binding `
    --member="serviceAccount:${RuntimeSa}" `
    --role=roles/bigquery.dataViewer `
    "${ProjectId}:${Dataset}.${View}"
  if ($LASTEXITCODE -ne 0) { throw "Failed to grant runtime access to $View" }
}

bq --project_id=$ProjectId show --format=prettyjson "${ProjectId}:${Dataset}.reporting_payroll"
```

The seed authorizes these views to read the private raw dataset. Preserve those
authorized-view ACL entries. The payroll view must retain its
`dsn_first_month` and `dsn_latest_month` labels; the agent uses them to resolve
periods. Do not solve access errors by granting the runtime BigQuery Admin or
raw-table access.

On Cloud Run, ADC automatically uses the attached `$RuntimeSa` through the
metadata service. Local ADC files and `GOOGLE_APPLICATION_CREDENTIALS` are
neither needed nor copied into the container.

## 4. Submit the automated build and deployment

Sign in as the authorized deployer if the administrator used a different
account. Confirm the active account:

```powershell
gcloud auth list
gcloud auth login $DeployerEmail
```

Inspect the upload manifest before the first deployment:

```powershell
gcloud meta list-files-for-upload
```

`.gcloudignore` allows only build inputs, application/configuration files,
tests, and the deployment scripts. `.dockerignore` separately limits the Docker
context. Neither should include `.env`, `.venv`, `node_modules`, existing
`frontend\dist`, `.git`, credential exports, or personal files. Review any
credentials accidentally placed *inside* allowed source/configuration folders
before submitting. The Python dependency manifest is pinned at the top level;
transitive dependencies and base-image tags can change between builds.

Build the substitution string and submit:

```powershell
$Substitutions = "_REGION=${Region},_REPOSITORY=${Repository},_SERVICE=${Service},_RUNTIME_SERVICE_ACCOUNT=${RuntimeAccount},_DATASET=${Dataset},_BIGQUERY_LOCATION=${BigQueryLocation},_VERTEX_LOCATION=${VertexLocation},_MODEL=${Model}"

gcloud builds submit . `
  --project=$ProjectId --region=$Region `
  --config=cloudbuild.yaml `
  --service-account=$BuildSaResource `
  --gcs-source-staging-dir="gs://${SourceBucket}/source" `
  --substitutions=$Substitutions
```

The pipeline stops on any failed step:

1. Validate required deployment substitutions.
2. Install backend dependencies and run Ruff and pytest.
3. Build the frontend with `npm ci`, Vitest, and TypeScript/Vite, then create
   the non-root Python runtime image.
4. Start that image and verify HTTP readiness, frontend assets, prompts, and
   conversation creation/clearing. This smoke check uses no model or warehouse.
5. Push an image tagged with the unique Cloud Build ID.
6. Deploy with IAM authentication required, the runtime service account, one
   Uvicorn worker, one configured maximum instance, session affinity, 1 CPU,
   1 GiB memory, concurrency 8, and a 300-second request timeout.

The process listens on `0.0.0.0:$PORT` (8080 by default). Cloud Run terminates
TLS; Uvicorn does not trust incoming forwarded headers.

On the **first** deployment, Cloud Run assigns the service URL. The script
discovers that URL and creates a second revision setting `DSN_PUBLIC_ORIGIN`.
The bootstrap revision accepts local hosts only and is not the final usable
revision. Later deployments reuse the assigned URL in a single deployment.
The configured exact HTTPS origin controls accepted hosts/write origins and
enables Secure, HttpOnly, SameSite=Strict conversation cookies. No wildcard
`*.run.app` or arbitrary Origin reflection is used.

The pipeline replaces the service environment with the deployment settings.
If you deliberately add other runtime variables or change resource limits,
maintain them in `scripts\deploy-cloud-run.sh`; a console-only edit can be
overwritten on the next deployment. Prompt/catalog changes also require a new
image because they are packaged in the container.

## 5. Grant private access and verify the service

An administrator grants each approved analyst the service-scoped invoker role
after the service exists:

```powershell
gcloud run services add-iam-policy-binding $Service `
  --project=$ProjectId --region=$Region `
  --member="user:${InvokerEmail}" --role=roles/run.invoker

$ServiceUrl = gcloud run services describe $Service `
  --project=$ProjectId --region=$Region --format="value(status.url)"

gcloud run services get-iam-policy $Service --project=$ProjectId --region=$Region
gcloud run services describe $Service --project=$ProjectId --region=$Region
```

Verify IAM has no `allUsers` or `allAuthenticatedUsers` bindings and that the
invoker IAM check is enabled. Organizational/inherited IAM can also grant
access; review it with your administrator. `ingress=all` lets authorized users
reach the service from their computers; it does **not** disable authentication.
Do not switch to `ingress=internal` unless you also provide an appropriate
network access path.

### Browser access

A private Cloud Run URL does not display a Google login page automatically.
In an analyst's terminal, authenticate and run the Cloud Run proxy:

```powershell
gcloud auth login
gcloud run services proxy $Service --project=$ProjectId --region=$Region --port=8080
```

Keep that terminal open and browse to **http://localhost:8080**. In a separate
terminal, a configuration-only health check is:

```powershell
Invoke-RestMethod http://localhost:8080/api/health | ConvertTo-Json -Depth 3
```

Use `localhost` with a modern Chrome/Edge browser: these support Secure cookies
on localhost despite the proxy's local HTTP connection. Do not expose the local
proxy to other users or use an arbitrary HTTP hostname. If browser policy
blocks these cookies, use an approved local HTTPS proxy instead; keep the
cloud cookie protection enabled.

Select a payroll comparison suggestion, keep the latest available month, and
click **Analyser**. Confirm that a real card includes a BigQuery job ID and
scope. Click an establishment to prepare a follow-up; confirm **no query runs
until Analyser**, then submit to append the second card. Switching a retained
card to a table should not create another BigQuery job.

### Authenticated HTTPS API check

For PowerShell API requests, use the actual HTTPS URL so Secure cookies work.
The calling account must have `roles/run.invoker`:

```powershell
$Token = gcloud auth print-identity-token
$Headers = @{ Authorization = "Bearer $Token"; Origin = $ServiceUrl }
Invoke-RestMethod "${ServiceUrl}/api/health" -Headers $Headers
Invoke-RestMethod "${ServiceUrl}/api/session" -Method Post `
  -Headers $Headers -SessionVariable DsnSession

$Body = @{
  question = "Compare la masse salariale brute par etablissement au dernier mois disponible."
  visualization = "bar"
} | ConvertTo-Json

$Answer = Invoke-RestMethod "${ServiceUrl}/api/analyze" -Method Post `
  -Headers $Headers -WebSession $DsnSession -ContentType "application/json" -Body $Body
$Answer.status
$Answer.presentation.card.evidence | ConvertTo-Json -Depth 5

Remove-Variable Token, Headers
```

The analysis incurs model/query usage. Health reporting `configured` checks
required settings only; it does **not** prove ADC, IAM, model availability,
dataset readiness, or a working live analysis. An unauthenticated request to
the direct service URL should be rejected by Cloud Run before reaching the app.

## 6. Redeploy and optionally enable deployment on push

For a manual redeployment, rerun the `gcloud builds submit` command in section 4
with the same substitutions. Each successful build gets a distinct image tag.
Configuration and prompt changes go through the same pipeline.

For automatic deployment on a protected GitHub branch:

1. Put these files in your GitHub repository. In Google Cloud Console, open
   **Cloud Build > Repositories**, create a regional GitHub connection, complete
   the GitHub App authorization, and link the intended repository. This human
   authorization cannot be replaced with a service-account key.
2. Copy the linked repository resource name and choose the protected branch.
   The example below deploys `main`; change it if your release branch differs.
3. Create the push trigger as an authorized maintainer:

```powershell
$RepoResource = "projects/${ProjectId}/locations/${Region}/connections/YOUR_CONNECTION/repositories/YOUR_REPOSITORY"
gcloud builds triggers create github `
  --name=dsn-main --project=$ProjectId --region=$Region `
  --repository=$RepoResource --branch-pattern="^main$" `
  --build-config=cloudbuild.yaml `
  --service-account=$BuildSaResource `
  --substitutions=$Substitutions
```

The trigger uses the linked repository, not your local staging bucket. Grant
the build identity source-object read access on any additional source bucket
used by that connection if required by its configuration. Protect the release
branch and review changes to deployment files: code running as the build
identity can deploy services and attach the runtime identity. Do not attach
this deploy trigger to untrusted pull requests or fork events. Configure
repository secret scanning; `.gcloudignore` does not remove a secret already
committed to GitHub.

## 7. Logs, troubleshooting, and rollback

```powershell
gcloud builds list --project=$ProjectId --region=$Region --limit=5
gcloud run services logs read $Service --project=$ProjectId --region=$Region --limit=50
gcloud run revisions list --service=$Service --project=$ProjectId --region=$Region
```

These diagnostic commands require the relevant build/run read and log-viewer
permissions; a service-scoped analyst invoker does not automatically have them.

| Symptom | Check |
|---|---|
| Direct URL returns 401/403 | Expected without an identity token. Use the authenticated proxy or HTTPS API example; verify the caller's invoker role. |
| Proxy cannot describe/find the service | Some CLI operations also require Cloud Run read access. An administrator can grant `roles/run.viewer` on this service to the affected operator. |
| Build cannot read source or write an image/logs | Check `$BuildSa`, staging-bucket Object Viewer, repository Writer, and Logs Writer bindings. |
| `iam.serviceAccounts.actAs` denied | The human needs Service Account User on `$BuildSa`; `$BuildSa` needs it on `$RuntimeSa`. |
| Container fails to start | Read revision logs. Check Linux image compatibility, `PORT`, 0.0.0.0 binding, installed dependencies, and packaged frontend/config files. |
| `Invalid host header` or `invalid_origin` | Check `DSN_PUBLIC_ORIGIN` equals `status.url`. Custom domains/revision-tag URLs need explicit origin configuration; wildcard hosts are not enabled. |
| `configuration_required` | Inspect deployed `DSN_PROJECT_ID`, `DSN_BIGQUERY_LOCATION`, `DSN_VERTEX_LOCATION`, and `DSN_MODEL`. Local `.env` is intentionally not uploaded. |
| BigQuery permission/location error | Check view-only grants, authorized-view ACLs, jobUser, and the actual dataset location. |
| `dataset_not_ready` | Check all reporting views exist and the payroll view has complete-month availability labels. |
| Model invocation fails | Check Vertex API, runtime Vertex permissions, model ID, location, organization policy, and quota. |
| Session expires / results disappear | Reload to establish a new session after instance replacement. Previous in-memory cards cannot be recovered; do not automatically replay billable analyses. |
| Request times out | Inspect model and BigQuery logs. Cloud Run timeout is 300 seconds; a disconnected/timed-out client does not guarantee downstream work or charges stop. |

If needed, an administrator can grant a proxy operator service-scoped read
access without deployment rights:

```powershell
gcloud run services add-iam-policy-binding $Service `
  --project=$ProjectId --region=$Region `
  --member="user:${InvokerEmail}" --role=roles/run.viewer
```

To roll back, select a previous **fully configured** revision from the revision
list, not the initial bootstrap revision:

```powershell
$PreviousRevision = "REPLACE_WITH_PREVIOUS_READY_REVISION"
gcloud run services update-traffic $Service --project=$ProjectId --region=$Region `
  --to-revisions="${PreviousRevision}=100"
```

Reload the browser afterward. Old in-memory state is not restored by rollback.
The next successful pipeline run explicitly returns traffic to its latest
revision; revert the faulty source/configuration before running it again.

## 8. Operational limits and costs

This deployment is a **private synthetic-data demo, not a durable multi-user
production service**. Conversations, result ownership, locks, and ADK sessions
remain in process memory. One worker, a maximum-instance setting of one, and
session affinity reduce routing surprises but do not guarantee a single
process across rollouts, replacements, or temporary scaling exceptions.
Scale-to-zero, restarts, deployments, and OOM termination lose all sessions.
Before horizontal scaling or a production rollout, use shared persistent
session/result storage, distributed concurrency controls, and appropriate
application-level user/data authorization.

IAM controls who can invoke the service; it does not provide per-analyst
warehouse permissions. All approved invokers use the same runtime identity and
can query the same three synthetic reporting views. Do not deploy real DSN
personal data under this demo's access/retention model.

Cloud Run, Cloud Build, Artifact Registry, source storage, Cloud Logging,
BigQuery, and Vertex AI can all incur costs. Min instances is zero; cold starts
are expected. The query billing limit and instance settings are not spending
caps. Configure billing budgets/alerts, model quotas, log/source retention,
and Artifact Registry cleanup policies separately. Build/image/source retention
continues after deleting the service. Avoid logging tokens or full DSN data.

To stop deployment-on-push and remove only the service, when intentionally
retiring this deployment:

```powershell
# Only if you created the optional trigger:
gcloud builds triggers delete dsn-main --project=$ProjectId --region=$Region
gcloud run services delete $Service --project=$ProjectId --region=$Region
```

Review retained images, source archives, logs, service accounts, IAM bindings,
and datasets separately. This runbook intentionally does not delete warehouse
data or recursively remove storage.

## References

- [Cloud Build deployment to Cloud Run](https://cloud.google.com/build/docs/deploying-builds/deploy-cloud-run)
- [User-managed build identities](https://cloud.google.com/build/docs/securing-builds/configure-user-specified-service-accounts)
- [Cloud Run deployment flags](https://cloud.google.com/sdk/gcloud/reference/run/deploy)
- [Authenticated local Cloud Run proxy](https://cloud.google.com/sdk/gcloud/reference/run/services/proxy)
- [BigQuery resource-level IAM](https://cloud.google.com/bigquery/docs/control-access-to-resources-iam)
