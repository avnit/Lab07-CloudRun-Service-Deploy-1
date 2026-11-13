variable "project_id" {
  type        = string
  description = "Throwaway lab GCP project to deploy into."
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "service_name" {
  type        = string
  default     = "watchlist"
  description = "Cloud Run service name (also the image name and the service-account prefix)."
}

variable "artifact_repository" {
  type        = string
  default     = "watchlist"
  description = "Artifact Registry Docker repository to create for the image."
}

variable "image" {
  type        = string
  default     = null
  description = "Full image reference to deploy. Leave null to build ../ with Cloud Build (needs the gcloud CLI)."
}

variable "mysql_image" {
  type        = string
  default     = "mysql:8.4.3"
  description = "MySQL sidecar image (pinned)."
}

variable "db_name" {
  type    = string
  default = "watchlist"
}

variable "db_root_password" {
  type        = string
  default     = null
  sensitive   = true
  description = "MySQL root password. Leave null to generate a random one. Never commit a real value."
}

variable "refresh_interval_minutes" {
  type        = number
  default     = 60
  description = "How often the app re-runs the fetcher to pull the latest content (it also runs at start-up). 0 disables auto-refresh."

  validation {
    condition     = var.refresh_interval_minutes >= 0
    error_message = "refresh_interval_minutes must be 0 or greater."
  }
}

variable "youtube_api_key" {
  type        = string
  default     = null
  sensitive   = true
  description = "YouTube Data API v3 key for the fetcher. Stored in Secret Manager. Leave null to skip the YouTube source. Never commit a real value."
}

variable "allow_unauthenticated" {
  type        = bool
  default     = false
  description = "Grant allUsers roles/run.invoker. Exposes an intentionally vulnerable app to the internet - lab projects only."
}
