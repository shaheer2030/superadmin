app_name = "superadmin"
app_title = "Superadmin"
app_publisher = "Superadmin"
app_description = "Central tenant provisioning"
app_email = "admin@example.com"
app_license = "MIT"

doctype_js = {"Tenant Company": "public/js/tenant_company.js"}

# Default apps after `bench new-site` for each tenant (override per record via Tenant Company → Install apps,
# or globally via sites/common_site_config.json → superadmin_tenant_install_apps).
superadmin_default_install_apps = ["erpnext"]
