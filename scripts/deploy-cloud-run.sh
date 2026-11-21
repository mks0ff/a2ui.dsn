#!/usr/bin/env bash
set -euo pipefail

: "${DEPLOY_PROJECT:?Set the Cloud Build project}"
: "${DEPLOY_BUILD_ID:?Cloud Build must supply BUILD_ID}"
: "${DEPLOY_REGION:?Set _REGION}"
: "${DEPLOY_REPOSITORY:?Set _REPOSITORY}"
: "${DEPLOY_SERVICE:?Set _SERVICE}"
: "${DEPLOY_RUNTIME_SERVICE_ACCOUNT:?Set _RUNTIME_SERVICE_ACCOUNT}"
: "${DEPLOY_DATASET:?Set _DATASET}"
: "${DEPLOY_BIGQUERY_LOCATION:?Set _BIGQUERY_LOCATION}"
: "${DEPLOY_VERTEX_LOCATION:?Set _VERTEX_LOCATION}"
: "${DEPLOY_MODEL:?Set _MODEL}"

if [[ ! "$DEPLOY_PROJECT" =~ ^[a-z][a-z0-9-]{4,61}[a-z0-9]$ ]] ||
   [[ ! "$DEPLOY_REGION" =~ ^[a-z][a-z0-9-]+$ ]] ||
   [[ ! "$DEPLOY_REPOSITORY" =~ ^[a-z][a-z0-9-]+$ ]] ||
   [[ ! "$DEPLOY_SERVICE" =~ ^[a-z]([a-z0-9-]{0,47}[a-z0-9])?$ ]] ||
   [[ ! "$DEPLOY_RUNTIME_SERVICE_ACCOUNT" =~ ^[a-z][a-z0-9-]{4,28}[a-z0-9]$ ]] ||
   [[ ! "$DEPLOY_DATASET" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]] ||
   [[ ! "$DEPLOY_BIGQUERY_LOCATION" =~ ^[a-zA-Z0-9-]+$ ]] ||
   [[ ! "$DEPLOY_VERTEX_LOCATION" =~ ^[a-zA-Z0-9-]+$ ]] ||
   [[ ! "$DEPLOY_MODEL" =~ ^[a-zA-Z0-9._:/-]+$ ]]; then
  echo "Invalid deployment setting. Check the substitutions in DEPLOY.md." >&2
  exit 1
fi

case "${1:-}" in
  validate) exit 0 ;;
  deploy) ;;
  *) echo "Usage: deploy-cloud-run.sh validate|deploy" >&2; exit 1 ;;
esac

image="$DEPLOY_REGION-docker.pkg.dev/$DEPLOY_PROJECT/$DEPLOY_REPOSITORY/$DEPLOY_SERVICE:$DEPLOY_BUILD_ID"
runtime_sa="$DEPLOY_RUNTIME_SERVICE_ACCOUNT@$DEPLOY_PROJECT.iam.gserviceaccount.com"
url="$(gcloud run services list --project="$DEPLOY_PROJECT" --region="$DEPLOY_REGION" \
  --filter="metadata.name=$DEPLOY_SERVICE" --format='value(status.url)')"

if [[ -n "$url" ]]; then
  public_members="$(gcloud run services get-iam-policy "$DEPLOY_SERVICE" \
    --project="$DEPLOY_PROJECT" --region="$DEPLOY_REGION" \
    --flatten='bindings[].members' \
    --filter='bindings.members=allUsers OR bindings.members=allAuthenticatedUsers' \
    --format='value(bindings.members)')"
  if [[ -n "$public_members" ]]; then
    echo "Refusing to reuse a service with public IAM bindings. Remove them first." >&2
    exit 1
  fi
fi

environment="DSN_PROJECT_ID=$DEPLOY_PROJECT,DSN_DATASET_ID=$DEPLOY_DATASET"
environment+=",DSN_BIGQUERY_LOCATION=$DEPLOY_BIGQUERY_LOCATION"
environment+=",DSN_VERTEX_LOCATION=$DEPLOY_VERTEX_LOCATION,DSN_MODEL=$DEPLOY_MODEL"
if [[ -n "$url" ]]; then
  environment+=",DSN_PUBLIC_ORIGIN=$url"
fi

gcloud run deploy "$DEPLOY_SERVICE" \
  --project="$DEPLOY_PROJECT" --region="$DEPLOY_REGION" \
  --image="$image" --service-account="$runtime_sa" \
  --no-allow-unauthenticated --invoker-iam-check --ingress=all \
  --port=8080 --cpu=1 --memory=1Gi --timeout=300s --concurrency=8 \
  --min=0 --min-instances=0 --max=1 --max-instances=1 --session-affinity \
  --set-env-vars="$environment" --quiet

if [[ -z "$url" ]]; then
  # Discover the assigned origin rather than guessing a Cloud Run hostname.
  url="$(gcloud run services describe "$DEPLOY_SERVICE" \
    --project="$DEPLOY_PROJECT" --region="$DEPLOY_REGION" --format='value(status.url)')"
  if [[ -z "$url" ]]; then
    echo "Cloud Run did not return a service URL." >&2
    exit 1
  fi
  gcloud run services update "$DEPLOY_SERVICE" \
    --project="$DEPLOY_PROJECT" --region="$DEPLOY_REGION" \
    --update-env-vars="DSN_PUBLIC_ORIGIN=$url" --quiet
fi

gcloud run services update-traffic "$DEPLOY_SERVICE" \
  --project="$DEPLOY_PROJECT" --region="$DEPLOY_REGION" --to-latest --quiet
printf 'Private service deployed: %s\nUse the authenticated proxy described in DEPLOY.md.\n' "$url"
