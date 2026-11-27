app_name = "superadmin"
app_title = "Superadmin"
app_publisher = "Superadmin"
app_description = "Central tenant provisioning (ERPNext version-agnostic)"
app_email = "admin@example.com"
app_license = "MIT"

doctype_js = {
	"Tenant Company": "public/js/tenant_company.js",
	"SaaS Plan": "public/js/saas_plan.js",
}

# Public portal assets
app_include_css = []
app_include_js = [
	"/assets/superadmin/js/desk_branding.js",
	"/assets/superadmin/js/setup_wizard_saas.js",
]
web_include_css = ["/assets/superadmin/css/portal.css"]

# Ensure www pages wrap into web.html when content-only templates are used
base_template_map = {
	r"home": "templates/web.html",
	r"signup": "templates/web.html",
	r"verify": "templates/web.html",
	r"portal-login": "templates/web.html",
	r"account": "templates/web.html",
	r"pricing": "templates/web.html",
}

# Tenants get erpnext only; branding JS is injected via site_config app_include_js
# (see system_branding.apply_branding_to_current_site) so a second app is not required.
superadmin_default_install_apps = ["erpnext"]
required_apps = []

after_migrate = [
	"superadmin.setup.ensure_portal_home",
	"superadmin.setup.ensure_system_branding_sidebar",
	"superadmin.setup.ensure_saas_defaults",
	"superadmin.setup.ensure_superadmin_sidebar_full",
]
after_install = [
	"superadmin.setup.ensure_portal_home",
	"superadmin.setup.ensure_system_branding_sidebar",
	"superadmin.setup.ensure_saas_defaults",
	"superadmin.setup.ensure_superadmin_sidebar_full",
]

scheduler_events = {
	"hourly": ["superadmin.limits.enforce_all_subscriptions"],
	"daily": ["superadmin.backup.enqueue_scheduled_backups"],
}

website_route_rules = [
	{"from_route": "/signup", "to_route": "signup"},
	{"from_route": "/verify", "to_route": "verify"},
	{"from_route": "/portal-login", "to_route": "portal-login"},
	{"from_route": "/account", "to_route": "account"},
	{"from_route": "/pricing", "to_route": "pricing"},
]
