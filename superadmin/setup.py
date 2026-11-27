"""Install/migrate helpers for public portal, branding, and SaaS defaults."""

from __future__ import annotations

import frappe


def ensure_portal_home():
	"""Point Website Settings home page to Superadmin landing for guests."""
	try:
		ws = frappe.get_single("Website Settings")
		if (ws.home_page or "").strip() in ("", "login", "me"):
			ws.home_page = "home"
			ws.save(ignore_permissions=True)
			frappe.db.commit()
	except Exception:
		frappe.log_error(title="superadmin ensure_portal_home")


def ensure_system_branding_sidebar():
	"""Ensure Superadmin sidebar contains System Branding under Settings."""
	try:
		if not frappe.db.exists("Sidebar", "Superadmin"):
			return
		sidebar = frappe.get_doc("Sidebar", "Superadmin")
		exists = any((row.link_to == "System Branding") for row in (sidebar.items or []))
		if exists:
			for row in sidebar.items:
				if row.link_to == "System Branding":
					row.label = "اعدادات النظام والحقوق"
			sidebar.save(ignore_permissions=True)
			frappe.db.commit()
			return

		insert_at = len(sidebar.items or [])
		for i, row in enumerate(sidebar.items or []):
			if row.link_to == "Superadmin Settings" or (row.label or "") in ("Settings", "إعدادات"):
				insert_at = i + 1
				break

		sidebar.append(
			"items",
			{
				"type": "Link",
				"label": "اعدادات النظام والحقوق",
				"link_type": "DocType",
				"link_to": "System Branding",
				"icon": "image",
				"idx": insert_at + 1,
			},
		)
		items = list(sidebar.items)
		new_row = items.pop()
		items.insert(insert_at, new_row)
		sidebar.set("items", [])
		for row in items:
			sidebar.append(
				"items",
				{
					"type": row.type,
					"label": row.label,
					"link_type": getattr(row, "link_type", None),
					"link_to": getattr(row, "link_to", None),
					"icon": getattr(row, "icon", None),
					"hidden": getattr(row, "hidden", 0),
				},
			)
		sidebar.save(ignore_permissions=True)
		frappe.db.commit()
	except Exception:
		frappe.log_error(title="superadmin ensure_system_branding_sidebar")


def ensure_saas_defaults():
	"""Seed plans, portal content, roles, server node, platform company."""
	try:
		from superadmin import permissions

		permissions.ensure_platform_roles()
	except Exception:
		frappe.log_error(title="superadmin ensure_platform_roles")

	_seed_saas_plans()
	_seed_portal_content()
	_seed_server_node()

	try:
		from superadmin.billing import ensure_platform_company

		ensure_platform_company()
	except Exception:
		frappe.log_error(title="superadmin ensure_platform_company migrate")


def _seed_saas_plans():
	"""Seed Basic / Business / Enterprise with apps vs modules separation."""
	if frappe.db.count("SaaS Plan"):
		_upgrade_existing_plans_entitlements()
		return

	def _mods(*names):
		label = {
			"Accounts": "المحاسبة",
			"Selling": "المبيعات",
			"Buying": "المشتريات",
			"Stock": "المخزون",
			"CRM": "CRM",
			"Projects": "المشاريع",
			"Manufacturing": "التصنيع",
			"Assets": "الأصول",
			"Support": "الدعم",
			"Setup": "الإعداد",
		}
		return [
			{
				"module_name": n,
				"module_label": label.get(n, n),
				"enabled": 1,
				"source_app": "erpnext",
			}
			for n in names
		]

	plans = [
		{
			"plan_code": "basic",
			"plan_name": "Basic",
			"is_active": 1,
			"is_public": 1,
			"is_free": 0,
			"trial_days": 7,
			"billing_period": "Monthly",
			"price_monthly": 99,
			"price_yearly": 990,
			"price": 99,
			"currency": "SAR",
			"max_users": 5,
			"max_companies": 1,
			"max_branches": 1,
			"max_storage_mb": 2048,
			"max_api_requests": 5000,
			"support_level": "Standard",
			"backup_included": 1,
			"sort_order": 1,
			"plan_apps": [{"app_name": "erpnext", "app_label": "ERPNext", "install": 1}],
			"plan_modules": _mods("Accounts", "Selling", "Buying", "Stock", "Setup"),
			"features": [
				{"feature_key": "accounting", "feature_label": "المحاسبة", "enabled": 1},
				{"feature_key": "sales_purchase", "feature_label": "المبيعات والمشتريات", "enabled": 1},
			],
		},
		{
			"plan_code": "business",
			"plan_name": "Business",
			"is_active": 1,
			"is_public": 1,
			"is_free": 0,
			"trial_days": 14,
			"billing_period": "Monthly",
			"price_monthly": 249,
			"price_yearly": 2490,
			"price": 249,
			"currency": "SAR",
			"max_users": 20,
			"max_companies": 3,
			"max_branches": 5,
			"max_storage_mb": 10240,
			"max_api_requests": 25000,
			"support_level": "Priority",
			"backup_included": 1,
			"sort_order": 2,
			"plan_apps": [{"app_name": "erpnext", "app_label": "ERPNext", "install": 1}],
			"plan_modules": _mods(
				"Accounts", "Selling", "Buying", "Stock", "CRM", "Projects", "HR", "Setup"
			),
			"features": [
				{"feature_key": "accounting", "feature_label": "المحاسبة", "enabled": 1},
				{"feature_key": "sales_purchase", "feature_label": "المبيعات والمشتريات", "enabled": 1},
				{"feature_key": "hr", "feature_label": "الموارد البشرية", "enabled": 1},
			],
		},
		{
			"plan_code": "enterprise",
			"plan_name": "Enterprise",
			"is_active": 1,
			"is_public": 1,
			"is_free": 0,
			"trial_days": 14,
			"billing_period": "Monthly",
			"price_monthly": 599,
			"price_yearly": 5990,
			"price": 599,
			"currency": "SAR",
			"max_users": 50,
			"max_companies": 10,
			"max_branches": 20,
			"max_storage_mb": 51200,
			"max_api_requests": 0,
			"support_level": "Dedicated",
			"backup_included": 1,
			"sort_order": 3,
			"plan_apps": [{"app_name": "erpnext", "app_label": "ERPNext", "install": 1}],
			"plan_modules": _mods(
				"Accounts",
				"Selling",
				"Buying",
				"Stock",
				"CRM",
				"Projects",
				"Manufacturing",
				"Assets",
				"Support",
				"Setup",
			),
			"features": [
				{"feature_key": "accounting", "feature_label": "المحاسبة", "enabled": 1},
				{"feature_key": "sales_purchase", "feature_label": "المبيعات والمشتريات", "enabled": 1},
				{"feature_key": "hr", "feature_label": "الموارد البشرية", "enabled": 1},
				{"feature_key": "manufacturing", "feature_label": "التصنيع والدعم المتقدم", "enabled": 1},
			],
		},
	]
	# HR module may not exist in Module Def on erpnext-only stacks — store as feature; map to Support/Projects if needed
	for p in plans:
		# Drop fictional HR module name if not in catalog — keep as feature only
		p["plan_modules"] = [m for m in p["plan_modules"] if m["module_name"] != "HR"]
		doc = frappe.get_doc({"doctype": "SaaS Plan", **p})
		doc.insert(ignore_permissions=True)
	frappe.db.commit()


def _upgrade_existing_plans_entitlements():
	"""Backfill plan_apps / plan_modules on older seeded plans."""
	from superadmin.entitlements import CATALOG_MODULES, sync_install_apps_field

	for name in frappe.get_all("SaaS Plan", pluck="name"):
		doc = frappe.get_doc("SaaS Plan", name)
		changed = False
		if not doc.get("plan_apps"):
			apps = (doc.install_apps or "erpnext").replace(",", "\n").splitlines()
			for a in apps:
				a = a.strip()
				if not a:
					continue
				doc.append("plan_apps", {"app_name": a, "app_label": a, "install": 1})
				changed = True
		if not doc.get("plan_modules"):
			# basic defaults by plan code / price
			if (doc.name or "").lower() in ("enterprise",) or (doc.price or 0) >= 500:
				mods = ["Accounts", "Selling", "Buying", "Stock", "CRM", "Projects", "Manufacturing", "Assets", "Support", "Setup"]
			elif (doc.name or "").lower() in ("business",) or (doc.price or 0) >= 200:
				mods = ["Accounts", "Selling", "Buying", "Stock", "CRM", "Projects", "Setup"]
			else:
				mods = ["Accounts", "Selling", "Buying", "Stock", "Setup"]
			labels = {m: ar for m, ar, _ in CATALOG_MODULES}
			for m in mods:
				doc.append(
					"plan_modules",
					{
						"module_name": m,
						"module_label": labels.get(m, m),
						"enabled": 1,
						"source_app": "erpnext",
					},
				)
				changed = True
		if getattr(doc, "price_monthly", None) in (None, 0) and doc.price:
			doc.price_monthly = doc.price
			changed = True
		if changed:
			sync_install_apps_field(doc)
			doc.save(ignore_permissions=True)
	frappe.db.commit()



def _seed_portal_content():
	try:
		pc = frappe.get_single("Portal Content")
	except Exception:
		return
	if (pc.hero_title or "").strip():
		return
	pc.hero_title = "شغّل شركتك على السحابة"
	pc.hero_subtitle = "منصة ORACPC — إعداد تلقائي لمواقع ERPNext معزولة لكل شركة"
	pc.hero_cta_label = "ابدأ الآن"
	pc.show_plans_section = 1
	pc.save(ignore_permissions=True)
	frappe.db.commit()


def _seed_server_node():
	if frappe.db.exists("Server Node", "primary"):
		return
	node = frappe.get_doc(
		{
			"doctype": "Server Node",
			"node_name": "primary",
			"is_default": 1,
			"status": "Active",
			"notes": "Multi-server orchestration deferred; single Free Tier node.",
		}
	)
	node.insert(ignore_permissions=True)
	frappe.db.commit()



SAAS_SIDEBAR_LINKS = [
	("باقات الاشتراك", "SaaS Plan", "plans"),
	("الاشتراكات", "SaaS Subscription", "subscription"),
	("الفواتير", "SaaS Invoice", "money"),
	("الكوبونات", "SaaS Coupon", "gift"),
	("تذاكر الدعم", "Platform Support Ticket", "support"),
	("النسخ الاحتياطي", "Tenant Backup Job", "database"),
	("محتوى البوابة", "Portal Content", "website"),
	("سجل التدقيق", "Platform Audit Log", "list"),
	("عقدة الخادم (مؤجل)", "Server Node", "server"),
]

CORE_SIDEBAR_LABELS = {
	"Tenant Company": "الشركات المستأجرة",
	"Superadmin Settings": "إعدادات المشرف",
	"System Branding": "اعدادات النظام والحقوق",
	"Tenant Signup": "طلبات التسجيل",
}


def ensure_superadmin_sidebar_full():
	"""Add SaaS DocType links to Superadmin sidebar and keep Arabic labels."""
	try:
		if not frappe.db.exists("Sidebar", "Superadmin"):
			return
		sidebar = frappe.get_doc("Sidebar", "Superadmin")
		existing = {row.link_to: row for row in (sidebar.items or [])}
		changed = False
		desired_labels = {link_to: label for label, link_to, _icon in SAAS_SIDEBAR_LINKS}
		desired_labels.update(CORE_SIDEBAR_LABELS)
		for label, link_to, icon in SAAS_SIDEBAR_LINKS:
			if link_to in existing:
				row = existing[link_to]
				if (row.label or "") != label:
					row.label = label
					changed = True
				continue
			sidebar.append(
				"items",
				{
					"type": "Link",
					"label": label,
					"link_type": "DocType",
					"link_to": link_to,
					"icon": icon,
				},
			)
			changed = True
		for row in sidebar.items or []:
			want = desired_labels.get(row.link_to)
			if want and (row.label or "") != want:
				row.label = want
				changed = True
		if changed:
			try:
				sidebar.flags.ignore_permissions = True
				# App-owned Sidebar requires developer mode to save via ORM
				old_dev = frappe.conf.get("developer_mode")
				frappe.conf.developer_mode = 1
				try:
					sidebar.save(ignore_permissions=True)
				finally:
					frappe.conf.developer_mode = old_dev
			except Exception:
				# Fallback: update labels directly
				for link_to, label in desired_labels.items():
					frappe.db.sql(
						"""
						update `tabSidebar Item`
						set label=%s
						where parent=%s and parenttype="Sidebar" and link_to=%s
						""",
						(label, "Superadmin", link_to),
					)
			frappe.db.commit()
	except Exception:
		frappe.log_error(title="superadmin ensure_superadmin_sidebar_full")
