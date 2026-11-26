output "web_project_id" {
  description = "Id of the console project."
  value       = vercel_project.web.id
}

output "api_project_id" {
  description = "Id of the API project."
  value       = vercel_project.api.id
}

output "api_settings" {
  description = "Non-secret environment variables managed on the API project."
  value       = sort(keys(local.api_settings))
}
