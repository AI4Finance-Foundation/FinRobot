#!/usr/bin/env bash
#
# FinRobot Equity Research — Google Cloud Run One-Click Deployment
#
# Prerequisites:
#   - gcloud CLI installed and authenticated
#   - config.ini with real API keys at finrobot_equity/core/config/config.ini
#
# Usage:
#   chmod +x deploy.gcloud.sh
#   ./deploy.gcloud.sh
#
set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────────────
PROJECT_ID="your-project-id"
REGION="us-central1"
SERVICE_NAME="finrobot-equity"
REPO_NAME="finrobot"                         # Artifact Registry repository
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${SERVICE_NAME}"
BUCKET_NAME="finrobot-reports-${PROJECT_ID}"
SQL_INSTANCE_NAME="finrobot-db"
DB_NAME="finrobot"
DB_USER="finrobot"
DB_PASS="$(openssl rand -base64 24)"         # random password, stored in secret
SECRET_NAME="finrobot-config-ini"
CONFIG_INI_PATH="finrobot_equity/core/config/config.ini"

echo "=========================================="
echo " FinRobot Cloud Run Deployment"
echo "=========================================="
echo "Project : ${PROJECT_ID}"
echo "Region  : ${REGION}"
echo "Service : ${SERVICE_NAME}"
echo ""

gcloud config set project "${PROJECT_ID}"

# ── Step 1: Create GCS Bucket ───────────────────────────────────────────────
echo "── Step 1/5: GCS Bucket ──"
if gsutil ls -b "gs://${BUCKET_NAME}" &>/dev/null; then
    echo "Bucket gs://${BUCKET_NAME} already exists, skipping."
else
    gsutil mb -l "${REGION}" "gs://${BUCKET_NAME}"
    echo "Created bucket gs://${BUCKET_NAME}"
fi

# ── Step 2: Cloud SQL PostgreSQL ─────────────────────────────────────────────
echo ""
echo "── Step 2/5: Cloud SQL ──"

# Enable API
gcloud services enable sqladmin.googleapis.com --quiet

if gcloud sql instances describe "${SQL_INSTANCE_NAME}" --project="${PROJECT_ID}" &>/dev/null; then
    echo "Cloud SQL instance ${SQL_INSTANCE_NAME} already exists, skipping creation."
else
    echo "Creating Cloud SQL instance (this may take a few minutes)..."
    gcloud sql instances create "${SQL_INSTANCE_NAME}" \
        --database-version=POSTGRES_15 \
        --tier=db-f1-micro \
        --region="${REGION}" \
        --storage-auto-increase \
        --quiet
fi

# Create user (ignore error if already exists)
gcloud sql users create "${DB_USER}" \
    --instance="${SQL_INSTANCE_NAME}" \
    --password="${DB_PASS}" \
    --quiet 2>/dev/null || echo "User ${DB_USER} may already exist, continuing."

# Create database (ignore error if already exists)
gcloud sql databases create "${DB_NAME}" \
    --instance="${SQL_INSTANCE_NAME}" \
    --quiet 2>/dev/null || echo "Database ${DB_NAME} may already exist, continuing."

SQL_CONNECTION_NAME=$(gcloud sql instances describe "${SQL_INSTANCE_NAME}" --format='value(connectionName)')
DATABASE_URL="postgresql+pg8000://${DB_USER}:${DB_PASS}@/${DB_NAME}?unix_sock=/cloudsql/${SQL_CONNECTION_NAME}/.s.PGSQL.5432"
echo "Cloud SQL connection: ${SQL_CONNECTION_NAME}"

# ── Step 3: Secret Manager — config.ini ──────────────────────────────────────
echo ""
echo "── Step 3/5: Secret Manager ──"

gcloud services enable secretmanager.googleapis.com --quiet

if [ ! -f "${CONFIG_INI_PATH}" ]; then
    echo "ERROR: ${CONFIG_INI_PATH} not found."
    echo "Copy config.ini.example to config.ini and fill in your API keys first."
    exit 1
fi

if gcloud secrets describe "${SECRET_NAME}" --project="${PROJECT_ID}" &>/dev/null; then
    echo "Updating existing secret ${SECRET_NAME}..."
    gcloud secrets versions add "${SECRET_NAME}" --data-file="${CONFIG_INI_PATH}" --quiet
else
    echo "Creating secret ${SECRET_NAME}..."
    gcloud secrets create "${SECRET_NAME}" --data-file="${CONFIG_INI_PATH}" --replication-policy=automatic --quiet
fi

# Grant Cloud Run service account access to the secret
PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')
SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
gcloud secrets add-iam-policy-binding "${SECRET_NAME}" \
    --member="serviceAccount:${SA}" \
    --role="roles/secretmanager.secretAccessor" \
    --quiet >/dev/null

# ── Step 4: Build & Push Docker Image ────────────────────────────────────────
echo ""
echo "── Step 4/5: Docker Build & Push ──"

gcloud services enable artifactregistry.googleapis.com --quiet

# Create Artifact Registry repo if not exists
gcloud artifacts repositories describe "${REPO_NAME}" \
    --location="${REGION}" --project="${PROJECT_ID}" &>/dev/null || \
    gcloud artifacts repositories create "${REPO_NAME}" \
        --repository-format=docker \
        --location="${REGION}" \
        --quiet

echo "Building and pushing image with Cloud Build..."
gcloud builds submit --tag "${IMAGE}" --quiet

# ── Step 5: Deploy Cloud Run ─────────────────────────────────────────────────
echo ""
echo "── Step 5/5: Cloud Run Deploy ──"

gcloud services enable run.googleapis.com --quiet

gcloud run deploy "${SERVICE_NAME}" \
    --image="${IMAGE}" \
    --region="${REGION}" \
    --platform=managed \
    --port=8001 \
    --memory=2Gi \
    --timeout=3600 \
    --allow-unauthenticated \
    --add-cloudsql-instances="${SQL_CONNECTION_NAME}" \
    --set-env-vars="DATABASE_URL=${DATABASE_URL}" \
    --update-secrets="/app/finrobot_equity/core/config/config.ini=${SECRET_NAME}:latest" \
    --execution-environment=gen2 \
    --add-volume=name=reports,type=cloud-storage,bucket="${BUCKET_NAME}" \
    --add-volume-mount=volume=reports,mount-path=/app/finrobot_equity/core/output \
    --quiet

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo "=========================================="
echo " Deployment Complete!"
echo "=========================================="
SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" --region="${REGION}" --format='value(status.url)')
echo "Service URL : ${SERVICE_URL}"
echo "GCS Bucket  : gs://${BUCKET_NAME}"
echo "Cloud SQL   : ${SQL_CONNECTION_NAME}"
echo ""
echo "Next steps:"
echo "  1. Visit ${SERVICE_URL} to verify the app loads"
echo "  2. Generate a report and check gs://${BUCKET_NAME} for output files"
echo "  3. Restart the service and confirm reports persist"
