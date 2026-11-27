# Copyright (c) 2026, Superadmin and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt


class SaaSPlan(Document):
	def validate(self):
		from superadmin.entitlements import sync_install_apps_field

		# Prefer explicit monthly/yearly; keep legacy `price` populated for billing helpers
		if flt(self.price_monthly) and not flt(self.price):
			self.price = self.price_monthly
		elif flt(self.price) and not flt(self.price_monthly):
			self.price_monthly = self.price

		sync_install_apps_field(self)

	def on_update(self):
		# Re-apply in background: install-app + with_site must not run inside savedocs
		# (slow + used to destroy frappe.local.request and break the HTTP save).
		if frappe.flags.in_migrate or frappe.flags.in_install:
			return
		if frappe.flags.get("skip_saas_plan_reapply"):
			return
		try:
			frappe.enqueue(
				"superadmin.superadmin.doctype.saas_plan.saas_plan.reapply_plan_to_subscribers",
				plan=self.name,
				queue="long",
				timeout=3600,
				enqueue_after_commit=True,
				job_id=f"saas-plan-reapply-{self.name}",
				deduplicate=True,
			)
		except Exception:
			frappe.log_error(title=f"saas_plan enqueue reapply {self.name}")


def reapply_plan_to_subscribers(plan: str | None = None, plan_doc=None):
	"""Background job: push plan apps/modules/limits to active subscribers."""
	if plan_doc is None:
		if not plan or not frappe.db.exists("SaaS Plan", plan):
			return
		plan_doc = frappe.get_doc("SaaS Plan", plan)

	from superadmin.entitlements import apply_entitlements_to_site, ensure_missing_apps_installed
	from superadmin.limits import apply_limits_to_site, get_limits_from_plan

	subs = frappe.get_all(
		"SaaS Subscription",
		filters={"plan": plan_doc.name, "status": ["in", ["Trial", "Active", "Grace", "Past Due"]]},
		fields=["name", "tenant_company"],
	)
	limits = get_limits_from_plan(plan_doc)
	for sub in subs:
		site = frappe.db.get_value("Tenant Company", sub.tenant_company, "site_name")
		if not site:
			continue
		try:
			ensure_missing_apps_installed(site, plan_doc)
			apply_limits_to_site(site, limits)
			apply_entitlements_to_site(site, plan_doc)
		except Exception:
			frappe.log_error(title=f"saas_plan reapply {plan_doc.name} -> {site}")


# Backwards-compatible alias
_reapply_plan_to_subscribers = reapply_plan_to_subscribers
