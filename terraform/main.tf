# =====================================================================
# INTENTIONALLY VULNERABLE CONFIG - LAB / SANDBOX USE ONLY.
# CM-0003 / CWE-312 + CWE-250: the MySQL root password is passed to both
# containers as a plaintext env value (visible on the Cloud Run revision
# and in Terraform state), and the app connects to MySQL as root.
# Expected fix: store the password in Secret Manager and reference it
# with value_source.secret_key_ref; give the app a least-privilege DB user.
# =====================================================================
#
# One Cloud Run service, two containers:
#   web    Flask + gunicorn, receives all HTTP traffic on :8080
#   mysql  MySQL sidecar, reachable from `web` on 127.0.0.1:3306
#
# The MySQL data directory is an in-memory volume, so the database is
# EPHEMERAL: every new instance starts empty and `web` re-seeds it from
# data/sources.json + data/catalog.json. Scaling is pinned to one instance
# because each instance has its own private database. For durable data use
# Cloud SQL instead.

terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  app_dir = abspath("${path.module}/..")

  # Everything that goes into the image. A change to any of these files
  # produces a new tag, a new Cloud Build, and a new Cloud Run revision.
  image_sources = [
    for f in sort(setunion([
      for pattern in ["Dockerfile", "requirements.txt", "app/**", "web/**", "data/**", "scripts/fetch_media.py"] :
      fileset(local.app_dir, pattern)
    ]...)) :
    f if !endswith(f, ".db") && !strcontains(f, "__pycache__")
  ]
  source_hash = substr(sha1(join("", [for f in local.image_sources : filesha1("${local.app_dir}/${f}")])), 0, 12)

  built_image = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}/${var.service_name}:${local.source_hash}"
  image       = coalesce(var.image, local.built_image)

  db_root_password = coalesce(var.db_root_password, random_password.db_root.result)

  # The YouTube source is optional: without a key the fetcher skips it.
  has_youtube_key = nonsensitive(var.youtube_api_key != null)

  labels = {
    app     = "antigravity-hermes-watchlist"
    purpose = "security-lab"
  }
}

# ----------------------------- APIs ----------------------------------------
resource "google_project_service" "required" {
  for_each = toset([
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "secretmanager.googleapis.com",
  ])
  service            = each.value
  disable_on_destroy = false
}

# ----------------------------- image ---------------------------------------
resource "google_artifact_registry_repository" "images" {
  location      = var.region
  repository_id = var.artifact_repository
  format        = "DOCKER"
  description   = "antigravity-hermes-watchlist lab images"
  labels        = local.labels

  depends_on = [google_project_service.required]
}

# Builds and pushes the image with Cloud Build (needs the gcloud CLI where
# Terraform runs). Skipped when var.image points at an image you built yourself.
resource "terraform_data" "image_build" {
  count            = var.image == null ? 1 : 0
  triggers_replace = [local.built_image]

  provisioner "local-exec" {
    command = "gcloud builds submit \"${local.app_dir}\" --tag \"${local.built_image}\" --project \"${var.project_id}\" --quiet"
  }

  depends_on = [google_project_service.required]
}

# ----------------------------- identity ------------------------------------
# Dedicated runtime identity with no project roles: the app calls no GCP APIs.
resource "google_service_account" "runtime" {
  account_id   = "${var.service_name}-sa"
  display_name = "Watchlist lab app runtime (no roles)"
}

resource "random_password" "db_root" {
  length  = 24
  special = false
}

# ----------------------------- fetcher secret ------------------------------
# YouTube Data API key for the background fetcher. Created only when
# var.youtube_api_key is set; only the runtime service account can read it.
resource "google_secret_manager_secret" "youtube_api_key" {
  count     = local.has_youtube_key ? 1 : 0
  secret_id = "${var.service_name}-youtube-api-key"
  labels    = local.labels

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_version" "youtube_api_key" {
  count       = local.has_youtube_key ? 1 : 0
  secret      = google_secret_manager_secret.youtube_api_key[0].id
  secret_data = var.youtube_api_key
}

resource "google_secret_manager_secret_iam_member" "youtube_api_key" {
  count     = local.has_youtube_key ? 1 : 0
  secret_id = google_secret_manager_secret.youtube_api_key[0].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

# ----------------------------- Cloud Run -----------------------------------
resource "google_cloud_run_v2_service" "watchlist" {
  name                = var.service_name
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false
  labels              = local.labels

  template {
    service_account                  = google_service_account.runtime.email
    execution_environment            = "EXECUTION_ENVIRONMENT_GEN2"
    max_instance_request_concurrency = 80
    timeout                          = "120s"

    scaling {
      min_instance_count = 1
      max_instance_count = 1
    }

    containers {
      name       = "web"
      image      = local.image
      depends_on = ["mysql"] # start (and health-check) mysql first

      ports {
        container_port = 8080
      }

      env {
        name  = "DB_HOST"
        value = "127.0.0.1"
      }
      env {
        name  = "DB_PORT"
        value = "3306"
      }
      env {
        name  = "DB_NAME"
        value = var.db_name
      }
      env {
        name  = "DB_USER"
        value = "root"
      }
      # VULNERABLE (CWE-312): credential passed as a plaintext env value.
      env {
        name  = "DB_PASSWORD"
        value = local.db_root_password
      }

      # Re-run the fetcher on this interval (and once at start-up) so the
      # catalog always holds the latest content. 0 disables it.
      env {
        name  = "REFRESH_INTERVAL_MINUTES"
        value = tostring(var.refresh_interval_minutes)
      }
      # The right way to pass a credential: a Secret Manager reference.
      dynamic "env" {
        for_each = local.has_youtube_key ? [1] : []
        content {
          name = "YOUTUBE_API_KEY"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.youtube_api_key[0].secret_id
              version = google_secret_manager_secret_version.youtube_api_key[0].version
            }
          }
        }
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle = false # keep CPU allocated so mysqld is never frozen
      }

      startup_probe {
        period_seconds    = 5
        failure_threshold = 24
        http_get {
          path = "/health"
          port = 8080
        }
      }
    }

    containers {
      name  = "mysql"
      image = var.mysql_image

      env {
        name  = "MYSQL_DATABASE"
        value = var.db_name
      }
      # VULNERABLE (CWE-312): credential passed as a plaintext env value.
      env {
        name  = "MYSQL_ROOT_PASSWORD"
        value = local.db_root_password
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "2Gi"
        }
        cpu_idle = false
      }

      volume_mounts {
        name       = "mysql-data"
        mount_path = "/var/lib/mysql"
      }

      # During first-boot initialisation mysqld runs with networking off,
      # so port 3306 only opens once the real server is ready.
      startup_probe {
        initial_delay_seconds = 5
        period_seconds        = 5
        failure_threshold     = 36
        tcp_socket {
          port = 3306
        }
      }
    }

    volumes {
      name = "mysql-data"
      empty_dir {
        medium     = "MEMORY"
        size_limit = "1Gi"
      }
    }
  }

  depends_on = [
    google_project_service.required,
    terraform_data.image_build,
    google_secret_manager_secret_iam_member.youtube_api_key,
  ]
}

# Off by default: this app is intentionally vulnerable. The lab's
# "internet-facing" Wiz findings need allow_unauthenticated = true.
resource "google_cloud_run_v2_service_iam_member" "public" {
  count    = var.allow_unauthenticated ? 1 : 0
  name     = google_cloud_run_v2_service.watchlist.name
  location = google_cloud_run_v2_service.watchlist.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}
