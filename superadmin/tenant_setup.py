"""Auto-complete ERPNext Setup Wizard for SaaS tenants.

Tenants must not pick modules in the wizard — the SaaS Plan is the source of truth.
During provision we finish setup with signup/company defaults + plan module flags.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Optional

import frappe
from frappe import _
from frappe.utils import cint, getdate

from superadmin.compat import with_site

# Platform defaults (overridable via Superadmin Settings / site_config)
_FALLBACK = {
	"country": "Saudi Arabia",
	"currency": "SAR",
	"language": "العربية",
	"timezone": "Asia/Riyadh",
	"chart_of_accounts": "Standard",
}

# Map plan modules → ERPNext Company.domain (single primary domain)
_MODULE_TO_DOMAIN = (
	("Manufacturing", "Manufacturing"),
	("Stock", "Distribution"),
	("Selling", "Retail"),
	("Projects", "Services"),
	("Accounts", "Services"),
)


def _settings_defaults() -> dict:
	out = dict(_FALLBACK)
	# common_site_config overrides
	for key, conf_key in (
		("country", "superadmin_default_country"),
		("currency", "superadmin_default_currency"),
		("language", "superadmin_default_language"),
		("timezone", "superadmin_default_timezone"),
		("chart_of_accounts", "superadmin_default_chart_of_accounts"),
	):
		val = frappe.conf.get(conf_key)
		if val:
			out[key] = val
	# Superadmin Settings (management site)
	try:
		if frappe.db.exists("DocType", "Superadmin Settings"):
			ss = frappe.get_single("Superadmin Settings")
			for key, attr in (
				("country", "default_country"),
				("currency", "default_currency"),
				("language", "default_language"),
				("timezone", "default_timezone"),
				("chart_of_accounts", "default_chart_of_accounts"),
			):
				val = (getattr(ss, attr, None) or "").strip()
				if val:
					out[key] = val
	except Exception:
		pass
	return out


def company_abbr_from_name(company_name: str) -> str:
	name = (company_name or "").strip()
	if not name:
		return "CO"
	parts = [p for p in re.split(r"[\s\-_./]+", name) if p]
	if len(parts) == 1:
		abbr = re.sub(r"[^A-Za-z0-9\u0600-\u06FF]", "", parts[0])[:5]
	else:
		abbr = "".join((p[0] for p in parts if p))[:5]
	abbr = (abbr or "CO").upper()
	# Arabic-only abbr: use first chars as-is (Company.abbr allows unicode)
	return abbr or "CO"


def fiscal_year_bounds(today: Optional[date] = None) -> tuple[str, str]:
	today = today or getdate()
	start = date(today.year, 1, 1)
	end = date(today.year, 12, 31)
	return start.isoformat(), end.isoformat()


def domain_for_modules(modules: list[str]) -> str:
	allowed = set(modules or [])
	for mod, domain in _MODULE_TO_DOMAIN:
		if mod in allowed:
			return domain
	return "Services"


def persona_flags_from_modules(modules: list[str]) -> dict:
	allowed = set(modules or [])
	return {
		"module_accounting": 1 if ("Accounts" in allowed or not allowed) else 0,
		"module_stock": 1 if "Stock" in allowed else 0,
		"module_manufacturing": 1 if "Manufacturing" in allowed else 0,
		"module_projects": 1 if "Projects" in allowed else 0,
	}


def build_setup_args(
	*,
	company_name: str,
	admin_email: str,
	plan_name: Optional[str] = None,
	full_name: Optional[str] = None,
) -> dict:
	"""Build frappe setup_wizard.setup_complete args from tenant + plan."""
	defaults = _settings_defaults()
	modules: list[str] = []
	if plan_name and frappe.db.exists("SaaS Plan", plan_name):
		from superadmin.entitlements import plan_enabled_modules

		modules = plan_enabled_modules(frappe.get_doc("SaaS Plan", plan_name))

	fy_start, fy_end = fiscal_year_bounds()
	flags = persona_flags_from_modules(modules)
	args = {
		"language": defaults["language"],
		"country": defaults["country"],
		"timezone": defaults["timezone"],
		"currency": defaults["currency"],
		"company_name": company_name,
		"company_abbr": company_abbr_from_name(company_name),
		"chart_of_accounts": defaults["chart_of_accounts"],
		"fy_start_date": fy_start,
		"fy_end_date": fy_end,
		"domain": domain_for_modules(modules),
		"email": admin_email,
		"full_name": full_name or company_name or admin_email,
		"enable_telemetry": 0,
		# Persona (telemetry only) — align with plan so UI intent matches entitlements
		"persona_industry": "Other",
		"persona_implementing_for": "My own company",
		"persona_company_size": "1-10",
		"persona_current_system": "Spreadsheets / Paper",
		**flags,
	}
	return args


def complete_tenant_setup_wizard(site_name: str, tenant_company) -> dict:
	"""Finish Setup Wizard on tenant site. Safe to call if already complete."""
	site_name = (site_name or "").strip()
	if not site_name:
		return {"ok": False, "error": "no site"}

	company_name = (getattr(tenant_company, "company_name", None) or "").strip() or site_name
	admin_email = (getattr(tenant_company, "admin_email", None) or "").strip()
	plan_name = (getattr(tenant_company, "plan", None) or "").strip() or None

	# Resolve plan from subscription if missing on Tenant Company
	if not plan_name and getattr(tenant_company, "subscription", None):
		plan_name = frappe.db.get_value("SaaS Subscription", tenant_company.subscription, "plan")

	args = build_setup_args(
		company_name=company_name,
		admin_email=admin_email,
		plan_name=plan_name,
		full_name=company_name,
	)

	result = {"ok": False, "site": site_name, "already_complete": False}

	def _inner():
		if frappe.is_setup_complete():
			result["ok"] = True
			result["already_complete"] = True
			return
		from frappe.desk.page.setup_wizard.setup_wizard import setup_complete

		frappe.set_user("Administrator")
		out = setup_complete(args)
		frappe.db.commit()
		result["ok"] = True
		result["setup_result"] = out
		result["args_summary"] = {
			"company_name": args["company_name"],
			"country": args["country"],
			"currency": args["currency"],
			"domain": args["domain"],
			"modules": {
				"accounting": args.get("module_accounting"),
				"stock": args.get("module_stock"),
				"manufacturing": args.get("module_manufacturing"),
				"projects": args.get("module_projects"),
			},
		}

	try:
		with_site(site_name, _inner)
	except Exception:
		frappe.log_error(title=f"superadmin tenant setup wizard {site_name}")
		result["error"] = "setup_failed"
		return result

	return result


def complete_setup_for_all_active_tenants() -> list[dict]:
	"""Ops helper: finish wizard on Active tenants that still show it."""
	rows = frappe.get_all(
		"Tenant Company",
		filters={"status": "Active", "archived": 0},
		fields=["name", "site_name", "company_name", "admin_email", "plan", "subscription"],
	)
	out = []
	for row in rows:
		if not row.site_name:
			continue
		doc = frappe.get_doc("Tenant Company", row.name)
		out.append(complete_tenant_setup_wizard(row.site_name, doc))
	return out
