output "service_url" {
  value       = google_cloud_run_v2_service.watchlist.uri
  description = "Cloud Run URL. Private unless allow_unauthenticated = true."
}

output "image" {
  value = local.image
}

output "service_account" {
  value = google_service_account.runtime.email
}

output "proxy_command" {
  value       = "gcloud run services proxy ${var.service_name} --region ${var.region} --project ${var.project_id} --port 8080"
  description = "Reach the private service on http://127.0.0.1:8080/."
}
