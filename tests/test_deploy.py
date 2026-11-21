import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BASH = shutil.which("bash")
if BASH is None and (git := shutil.which("git")):
    candidate = Path(git).resolve().parent.parent / "bin" / "bash.exe"
    if candidate.is_file():
        BASH = str(candidate)
pytestmark = pytest.mark.skipif(BASH is None, reason="Deployment script requires Bash.")

STUB = r"""
gcloud() {
  printf 'GCLOUD %s\n' "$*" >&2
  case "$*" in
    "run services list "*)
      if [[ "${FAIL_LIST:-}" == yes ]]; then return 3; fi
      printf '%s' "${EXISTING_URL:-}" ;;
    "run services get-iam-policy "*) printf '%s' "${PUBLIC_MEMBERS:-}" ;;
    "run services describe "*) printf '%s' 'https://dsn-example.run.app' ;;
  esac
}
export -f gcloud
bash scripts/deploy-cloud-run.sh deploy
"""


def deploy(**overrides):
    env = {
        **os.environ,
        "DEPLOY_PROJECT": "dsn-example",
        "DEPLOY_BUILD_ID": "build-123",
        "DEPLOY_REGION": "europe-west1",
        "DEPLOY_REPOSITORY": "dsn-containers",
        "DEPLOY_SERVICE": "dsn-atelier",
        "DEPLOY_RUNTIME_SERVICE_ACCOUNT": "dsn-runtime",
        "DEPLOY_DATASET": "dsn_demo",
        "DEPLOY_BIGQUERY_LOCATION": "EU",
        "DEPLOY_VERTEX_LOCATION": "global",
        "DEPLOY_MODEL": "test-model",
        "EXISTING_URL": "",
        "PUBLIC_MEMBERS": "",
        "FAIL_LIST": "",
        **overrides,
    }
    return subprocess.run(
        [BASH, "-c", STUB], cwd=ROOT, env=env, text=True, capture_output=True, check=False
    )


def test_new_service_discovers_origin_and_stays_private():
    result = deploy()
    assert result.returncode == 0, result.stderr
    assert "--no-allow-unauthenticated --invoker-iam-check" in result.stderr
    assert "--max=1 --max-instances=1" in result.stderr
    assert "--service-account=dsn-runtime@dsn-example.iam.gserviceaccount.com" in result.stderr
    assert "--update-env-vars=DSN_PUBLIC_ORIGIN=https://dsn-example.run.app" in result.stderr
    assert "services update-traffic" in result.stderr
    assert "Private service deployed" in result.stdout


def test_existing_service_sets_exact_origin_without_bootstrap_revision():
    result = deploy(EXISTING_URL="https://dsn-example.run.app")
    assert result.returncode == 0, result.stderr
    assert ",DSN_PUBLIC_ORIGIN=https://dsn-example.run.app" in result.stderr
    assert "GCLOUD run services update " not in result.stderr


def test_public_service_is_rejected_before_deployment():
    result = deploy(EXISTING_URL="https://dsn-example.run.app", PUBLIC_MEMBERS="allUsers")
    assert result.returncode != 0
    assert "public IAM bindings" in result.stderr
    assert "GCLOUD run deploy" not in result.stderr


def test_discovery_errors_are_not_treated_as_missing_service():
    result = deploy(FAIL_LIST="yes")
    assert result.returncode != 0
    assert "GCLOUD run deploy" not in result.stderr
    assert "Private service deployed" not in result.stdout


@pytest.mark.parametrize("model", ["", "model,DSN_PUBLIC_ORIGIN=https://unrelated.example"])
def test_missing_or_invalid_substitutions_fail_before_cloud_calls(model):
    result = deploy(DEPLOY_MODEL=model)
    assert result.returncode != 0
    assert "GCLOUD " not in result.stderr
