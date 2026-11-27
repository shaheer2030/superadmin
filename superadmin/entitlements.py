"""Plan entitlements: distinguish Frappe apps vs ERPNext modules.

- Apps (e.g. hrms): installed on the tenant site via bench install-app.
- Modules (e.g. Accounts, Stock): already inside an installed app; gated with
  Module Profile (block_modules) + role stripping on the tenant site.
"""

from __future__ import annotations

import json
from typing import Iterable, Optional

import frappe
from frappe import _
from frappe.utils import cint

from superadmin import audit
from superadmin.compat import app_on_bench, with_site

# Core ERPNext modules shown in plan UI (label_ar, module Def name)
CATALOG_MODULES = [
	("Accounts", "المحاسبة", "erpnext"),
	("Selling", "المبيعات", "erpnext"),
	("Buying", "المشتريات", "erpnext"),
	("Stock", "المخزون", "erpnext"),
	("CRM", "إدارة علاقات العملاء", "erpnext"),
	("Projects", "المشاريع", "erpnext"),
	("Manufacturing", "التصنيع", "erpnext"),
	("Assets", "الأصول", "erpnext"),
	("Support", "الدعم", "erpnext"),
	("Quality Management", "إدارة الجودة", "erpnext"),
	("Maintenance", "الصيانة", "erpnext"),
	("Setup", "الإعداد", "erpnext"),
	# Frappe HR (hrms) — separate app; modules appear after hrms is on the bench
	("HR", "الموارد البشرية", "hrms"),
	("Payroll", "الرواتب", "hrms"),
	("Leaves", "الإجازات", "hrms"),
	("Shift and Attendance", "الحضور والورديات", "hrms"),
	("Expenses", "المصروفات", "hrms"),
	("Performance", "الأداء", "hrms"),
	("Recruitment", "التوظيف", "hrms"),
	("Tax and Benefits", "الضرائب والمزايا", "hrms"),
	("Tenure", "مدة الخدمة", "hrms"),
	("HR Setup", "إعداد الموارد البشرية", "hrms"),
]

# Roles typically required to *use* a module — removed when module is disabled.
MODULE_ROLES = {
	"Accounts": ["Accounts Manager", "Accounts User", "Auditor"],
	"Selling": ["Sales Manager", "Sales User", "Sales Master Manager"],
	"Buying": ["Purchase Manager", "Purchase User", "Purchase Master Manager"],
	"Stock": ["Stock Manager", "Stock User", "Item Manager"],
	"CRM": ["Sales User", "Sales Manager"],
	"Projects": ["Projects Manager", "Projects User"],
	"Manufacturing": ["Manufacturing Manager", "Manufacturing User"],
	"Assets": ["Accounts Manager"],
	"Support": ["Support Team", "Support Manager"],
	"Quality Management": ["Quality Manager"],
	"Maintenance": ["Maintenance Manager", "Maintenance User"],
	"HR": ["HR Manager", "HR User", "Employee"],
	"Payroll": ["HR Manager", "HR User"],
	"Leaves": ["HR Manager", "HR User", "Leave Approver"],
	"Shift and Attendance": ["HR Manager", "HR User"],
	"Expenses": ["Expense Approver", "HR User"],
	"Performance": ["HR Manager", "HR User"],
	"Recruitment": ["HR Manager", "HR User"],
}

# Always keep these modules visible (desk/setup basics)
ALWAYS_ALLOWED_MODULES = {"Setup", "Desk", "Core", "Website", "Workflow", "Email", "Printing", "Custom"}


# Never offer these as tenant install targets in the plan UI.
_NON_TENANT_APPS = frozenset({"frappe", "superadmin"})


def list_bench_apps() -> list[dict]:
	"""Apps present on the bench (installable on tenants) — not ERPNext modules."""
	from frappe.utils import get_bench_path
	import os

	apps_dir = os.path.join(get_bench_path(), "apps")
	out = []
	if not os.path.isdir(apps_dir):
		return out
	for name in sorted(os.listdir(apps_dir)):
		if name.startswith(".") or name in _NON_TENANT_APPS:
			continue
		path = os.path.join(apps_dir, name)
		if os.path.isdir(path):
			out.append(
				{
					"app_name": name,
					"app_label": name,
					"kind": "frappe_app",
					"on_bench": True,
				}
			)
	return out


@frappe.whitelist()
def get_installable_app_options():
	"""Select options for SaaS Plan App.app_name (newline-separated)."""
	from superadmin.permissions import only_platform

	only_platform("Platform Admin", "Platform Billing")
	names = [a["app_name"] for a in list_bench_apps()]
	# Leading newline → blank first option in Frappe Select
	return "\n" + "\n".join(names)


@frappe.whitelist()
def get_plan_module_options():
	"""Select options for SaaS Plan Module.module_name (newline-separated)."""
	from superadmin.permissions import only_platform

	only_platform("Platform Admin", "Platform Billing")
	names = [m["module_name"] for m in list_catalog_modules()]
	return "\n" + "\n".join(names)


@frappe.whitelist()
def get_module_meta(module_name: Optional[str] = None):
	"""Return label + source_app for a catalog module (for child-table autofill)."""
	from superadmin.permissions import only_platform

	only_platform("Platform Admin", "Platform Billing")
	module_name = (module_name or "").strip()
	if not module_name:
		return {}
	for m in list_catalog_modules():
		if m["module_name"] == module_name:
			return {
				"module_name": m["module_name"],
				"module_label": m.get("module_label") or m["module_name"],
				"source_app": m.get("source_app") or "erpnext",
			}
	return {"module_name": module_name, "module_label": module_name, "source_app": "erpnext"}


@frappe.whitelist()
def get_modules_for_apps(apps=None):
	"""Modules belonging to the given Frappe apps (for auto-fill on plan_apps change)."""
	from superadmin.permissions import only_platform

	only_platform("Platform Admin", "Platform Billing")
	if isinstance(apps, str):
		raw = apps.strip()
		if raw.startswith("["):
			apps = json.loads(raw)
		else:
			apps = [p.strip() for p in raw.replace("\n", ",").split(",") if p.strip()]
	app_set = {str(a).strip() for a in (apps or []) if str(a).strip()}
	if not app_set:
		return []

	# Prefer curated catalog rows for SaaS plans; fall back to Module Def rows for that app.
	curated = [
		m
		for m in list_catalog_modules()
		if (m.get("source_app") or "erpnext") in app_set and m.get("in_catalog")
	]
	if curated:
		return curated
	return [m for m in list_catalog_modules() if (m.get("source_app") or "") in app_set]


def list_catalog_modules() -> list[dict]:
	"""Static curated list + live Module Def rows from erpnext (and other apps except frappe/superadmin)."""
	by_name = {
		m: {
			"module_name": m,
			"module_label": ar,
			"source_app": app,
			"kind": "erpnext_module",
			"in_catalog": True,
		}
		for m, ar, app in CATALOG_MODULES
	}
	try:
		rows = frappe.get_all(
			"Module Def",
			filters={"app_name": ["not in", ["frappe", "superadmin"]]},
			fields=["name", "app_name"],
			order_by="app_name asc, name asc",
		)
		for row in rows:
			name = row.name
			if name in by_name:
				by_name[name]["source_app"] = row.app_name or by_name[name]["source_app"]
				continue
			by_name[name] = {
				"module_name": name,
				"module_label": name,
				"source_app": row.app_name or "erpnext",
				"kind": "erpnext_module",
				"in_catalog": False,
			}
	except Exception:
		pass
	return sorted(by_name.values(), key=lambda d: (d.get("source_app") or "", d["module_name"]))


@frappe.whitelist()
def get_entitlement_catalog(plan: Optional[str] = None):
	"""Desk helper: apps vs modules for plan builders, with current plan selection."""
	from superadmin.permissions import only_platform

	only_platform("Platform Admin", "Platform Billing")
	modules = list_catalog_modules()
	selected_modules = set()
	selected_apps = set()
	if plan and frappe.db.exists("SaaS Plan", plan):
		doc = frappe.get_doc("SaaS Plan", plan)
		for row in doc.get("plan_modules") or []:
			if row.module_name and cint(row.enabled):
				selected_modules.add(row.module_name)
		for row in doc.get("plan_apps") or []:
			if row.app_name and cint(row.install):
				selected_apps.add(row.app_name)

	for m in modules:
		m["selected"] = m["module_name"] in selected_modules
		m["missing_from_plan"] = m["module_name"] not in selected_modules

	apps = list_bench_apps()
	for a in apps:
		a["selected"] = a["app_name"] in selected_apps

	return {
		"apps": apps,
		"modules": modules,
		"selected_modules": sorted(selected_modules),
		"selected_apps": sorted(selected_apps),
		"note": _(
			"Apps are installed with bench. Modules live inside an installed app and are gated by Module Profile + roles."
		),
	}


def plan_install_app_names(plan_doc) -> list[str]:
	names = []
	for row in plan_doc.get("plan_apps") or []:
		if cint(row.install) and (row.app_name or "").strip():
			names.append(row.app_name.strip())
	if names:
		return names
	# legacy Small Text
	raw = (plan_doc.install_apps or "").strip()
	if not raw:
		return ["erpnext"] if app_on_bench("erpnext") else []
	parts = []
	for chunk in raw.replace(",", "\n").splitlines():
		a = chunk.strip()
		if a:
			parts.append(a)
	return parts or (["erpnext"] if app_on_bench("erpnext") else [])


def plan_enabled_modules(plan_doc) -> list[str]:
	enabled = []
	for row in plan_doc.get("plan_modules") or []:
		if cint(row.enabled) and (row.module_name or "").strip():
			enabled.append(row.module_name.strip())
	if enabled:
		return enabled
	# default: core commercial modules if table empty (backward compatible)
	return ["Accounts", "Selling", "Buying", "Stock", "Setup"]


def plan_blocked_modules(plan_doc) -> list[str]:
	allowed = set(plan_enabled_modules(plan_doc)) | ALWAYS_ALLOWED_MODULES
	# Block catalog modules not enabled; leave unknown modules alone
	blocked = []
	for name, _ar, _app in CATALOG_MODULES:
		if name not in allowed and name not in ALWAYS_ALLOWED_MODULES:
			blocked.append(name)
	return blocked


def sync_install_apps_field(plan_doc) -> None:
	"""Keep legacy install_apps text in sync with plan_apps child table."""
	apps = plan_install_app_names(plan_doc)
	plan_doc.install_apps = "\n".join(apps)


def apply_entitlements_to_site(site_name: str, plan_doc) -> dict:
	"""Server-side: Module Profile + role strip + site_config entitlement keys."""
	site_name = (site_name or "").strip()
	if not site_name:
		return {"ok": False, "error": "no site"}

	allowed_modules = plan_enabled_modules(plan_doc)
	blocked = plan_blocked_modules(plan_doc)
	apps = plan_install_app_names(plan_doc)
	profile_name = f"Plan {plan_doc.name}"

	# site_config entitlements (auditable + usable by future tenant hooks)
	from superadmin.limits import _write_site_config_keys

	_write_site_config_keys(
		site_name,
		{
			"superadmin_plan": plan_doc.name,
			"superadmin_allowed_apps": json.dumps(apps),
			"superadmin_allowed_modules": json.dumps(allowed_modules),
			"superadmin_blocked_modules": json.dumps(blocked),
			"superadmin_max_users": plan_doc.max_users,
			"superadmin_max_companies": plan_doc.max_companies,
			"superadmin_max_branches": getattr(plan_doc, "max_branches", None),
			"superadmin_max_storage_mb": plan_doc.max_storage_mb,
			"superadmin_max_api_requests": getattr(plan_doc, "max_api_requests", None),
		},
	)

	result = {"profile": profile_name, "blocked": blocked, "apps": apps}

	def _inner():
		_ensure_module_profile(profile_name, blocked)
		_assign_profile_to_users(profile_name)
		_strip_roles_for_blocked_modules(blocked)
		# Tenant must not log in as Administrator (full permission bypass).
		lock_tenant_root_administrator()
		result["users_updated"] = True
		result["root_admin_locked"] = True

	try:
		with_site(site_name, _inner)
	except Exception:
		frappe.log_error(title=f"superadmin entitlements {site_name}")
		result["error"] = "apply_failed"
		return result

	audit.log_action(
		"entitlements_applied",
		"SaaS Plan",
		plan_doc.name,
		f"site={site_name}; apps={apps}; blocked={blocked}",
	)
	return result


def _ensure_module_profile(profile_name: str, blocked: Iterable[str]) -> None:
	blocked = list(blocked)
	if frappe.db.exists("Module Profile", profile_name):
		doc = frappe.get_doc("Module Profile", profile_name)
		doc.set("block_modules", [])
		for m in blocked:
			doc.append("block_modules", {"module": m})
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc(
			{
				"doctype": "Module Profile",
				"module_profile_name": profile_name,
				"block_modules": [{"module": m} for m in blocked],
			}
		)
		doc.insert(ignore_permissions=True)
	frappe.db.commit()


def _assign_profile_to_users(profile_name: str) -> None:
	"""Apply Module Profile to every desk user including Administrator.

	Must use User.save() so validate() copies block_modules from the profile.
	db.set_value alone leaves block_modules empty and desk stays unrestricted.
	Tenant company admins are renters: they must receive the same plan gates.
	"""
	users = frappe.get_all(
		"User",
		filters={
			"enabled": 1,
			"user_type": "System User",
			"name": ["!=", "Guest"],
		},
		pluck="name",
	)
	for user_name in users:
		try:
			user = frappe.get_doc("User", user_name)
			user.module_profile = profile_name
			user.flags.ignore_permissions = True
			user.flags.ignore_password_policy = True
			user.save()
		except Exception:
			frappe.log_error(title=f"superadmin assign module profile {user_name}")
	frappe.db.commit()


def _strip_roles_for_blocked_modules(blocked: Iterable[str]) -> None:
	"""Remove module roles for blocked modules from all desk users except Guest.

	Includes System Manager users (tenant company owners). Keeps the System Manager
	role itself so they can still administer allowed modules / users / settings.
	Administrator keeps all roles in Frappe core; navigation is gated via Module Profile.
	"""
	roles_to_remove = set()
	for mod in blocked:
		for role in MODULE_ROLES.get(mod, []):
			roles_to_remove.add(role)
	if not roles_to_remove:
		return

	users = frappe.get_all(
		"User",
		filters={
			"enabled": 1,
			"user_type": "System User",
			"name": ["not in", ["Administrator", "Guest"]],
		},
		pluck="name",
	)
	for user_name in users:
		user = frappe.get_doc("User", user_name)
		new_roles = [r for r in user.roles if r.role not in roles_to_remove]
		if len(new_roles) == len(user.roles):
			continue
		user.set("roles", [])
		for r in new_roles:
			user.append("roles", {"role": r.role})
		user.flags.ignore_permissions = True
		user.save()
	frappe.db.commit()


def lock_tenant_root_administrator() -> str:
	"""Rotate Administrator password so the tenant cannot use the root bypass account.

	Frappe grants Administrator every permission and ignores DocPerm. SaaS tenants must
	log in with their admin_email user (plan-gated). Platform recovery: bench set-admin-password.
	Returns the new random password (caller may discard).
	"""
	from frappe.utils.password import update_password

	secret = frappe.generate_hash(length=32)
	if frappe.db.exists("User", "Administrator"):
		update_password("Administrator", secret)
		# Keep enabled for bench/maintenance, but desk login secret is unknown to the tenant.
		frappe.db.commit()
	return secret


def roles_for_allowed_modules(allowed_modules: Iterable[str]) -> list[str]:
	"""Map plan-enabled modules to ERPNext roles (plus System Manager)."""
	allowed = set(allowed_modules) | ALWAYS_ALLOWED_MODULES
	roles = {"System Manager", "Desk User"}
	for mod, mod_roles in MODULE_ROLES.items():
		if mod in allowed:
			roles.update(mod_roles)
	# Always useful on any commercial plan
	roles.update({"Report Manager", "Workspace Manager", "Analytics", "Auditor"})
	return sorted(roles)


def ensure_missing_apps_installed(site_name: str, plan_doc) -> list[str]:
	"""Install missing Frappe apps required by the plan (never uninstall on downgrade)."""
	from superadmin.compat import find_bench_executable
	from superadmin.tenant_access import _run_bench_command, _site_exists
	from frappe.utils import get_bench_path
	import os

	site_name = (site_name or "").strip()
	if not site_name or not _site_exists(site_name):
		return []

	installed_path = os.path.join(get_bench_path(), "sites", site_name, "site_config.json")
	try:
		cfg = json.loads(open(installed_path, encoding="utf-8").read())
		have = set(cfg.get("installed_apps") or [])
	except Exception:
		have = set()

	bench = find_bench_executable()
	cwd = get_bench_path()
	installed_now = []
	for app in plan_install_app_names(plan_doc):
		if app in have or app == "frappe":
			continue
		if not app_on_bench(app):
			frappe.log_error(title=f"plan app missing on bench: {app}")
			continue
		try:
			_run_bench_command([bench, "--site", site_name, "install-app", app], cwd, timeout=3600)
			installed_now.append(app)
			have.add(app)
		except Exception:
			frappe.log_error(title=f"install-app failed {app} on {site_name}")
	return installed_now
