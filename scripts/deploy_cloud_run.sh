#!/usr/bin/env bash
# Build the image with Cloud Build and deploy cloudrun/service.yaml
# (web + MySQL sidecar) to Cloud Run.
#
#   export PROJECT_ID=my-lab-project        # required
#   export REGION=us-central1               # optional
#   ./scripts/deploy_cloud_run.sh --dry-run # print the commands only
#   ./scripts/deploy_cloud_run.sh           # deploy, IAM-authenticated access only
#   ./scripts/deploy_cloud_run.sh --public  # also allow unauthenticated access
#
# This app is INTENTIONALLY VULNERABLE. --public exposes it to the internet
# (what the lab's "internet-facing" Wiz findings expect); use it only in a
# throwaway lab project and delete the service afterwards:
#   gcloud run services delete watchlist --region "$REGION" --project "$PROJECT_ID"
set -euo pipefail
cd "$(dirname "$0")/.."

DRY_RUN=false
PUBLIC=false
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --public)  PUBLIC=true ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

: "${PROJECT_ID:?set PROJECT_ID to the lab GCP project}"
REGION="${REGION:-us-central1}"
AR_REPO="${AR_REPO:-watchlist}"
SERVICE="watchlist"
TAG="${TAG:-$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/${SERVICE}:${TAG}"
RENDERED="$(mktemp)"
trap 'rm -f "$RENDERED"' EXIT

run() {
  echo "+ $*"
  if [ "$DRY_RUN" = false ]; then "$@"; fi
}

sed "s|\${IMAGE}|${IMAGE}|g" cloudrun/service.yaml > "$RENDERED"

run gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
  cloudbuild.googleapis.com --project "$PROJECT_ID"

if [ "$DRY_RUN" = true ] || ! gcloud artifacts repositories describe "$AR_REPO" \
     --location "$REGION" --project "$PROJECT_ID" >/dev/null 2>&1; then
  run gcloud artifacts repositories create "$AR_REPO" --repository-format docker \
    --location "$REGION" --project "$PROJECT_ID" \
    --description "antigravity-hermes-watchlist lab images"
fi

run gcloud builds submit . --tag "$IMAGE" --project "$PROJECT_ID"
run gcloud run services replace "$RENDERED" --region "$REGION" --project "$PROJECT_ID"

if [ "$PUBLIC" = true ]; then
  run gcloud run services add-iam-policy-binding "$SERVICE" --region "$REGION" \
    --project "$PROJECT_ID" --member allUsers --role roles/run.invoker
else
  echo "Service is private. Reach it with:"
  echo "  gcloud run services proxy $SERVICE --region $REGION --project $PROJECT_ID --port 8080"
fi

if [ "$DRY_RUN" = true ]; then
  echo "--- rendered service.yaml (dry run, nothing was deployed) ---"
  cat "$RENDERED"
else
  gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT_ID" \
    --format 'value(status.url)'
fi
