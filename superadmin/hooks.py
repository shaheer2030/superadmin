app_name = "superadmin"
app_title = "Superadmin"
app_publisher = "Superadmin"
app_description = "Central tenant provisioning (ERPNext version-agnostic)"
app_email = "admin@example.com"
app_license = "MIT"

doctype_js = {"Tenant Company": "public/js/tenant_company.js"}

# Public portal assets
app_include_css = []
web_include_css = ["/assets/superadmin/css/portal.css"]

# Ensure www pages wrap into web.html when content-only templates are used
base_template_map = {
	r"home": "templates/web.html",
	r"signup": "templates/web.html",
	r"verify": "templates/web.html",
	r"portal-login": "templates/web.html",
}

superadmin_default_install_apps = ["erpnext"]
required_apps = []

after_migrate = ["superadmin.setup.ensure_portal_home"]
after_install = ["superadmin.setup.ensure_portal_home"]

website_route_rules = [
	{"from_route": "/signup", "to_route": "signup"},
	{"from_route": "/verify", "to_route": "verify"},
	{"from_route": "/portal-login", "to_route": "portal-login"},
]
