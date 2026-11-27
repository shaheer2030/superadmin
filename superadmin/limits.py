"""Subscription limits and enforcement for tenant sites."""

from __future__ import annotations

import json
from typing import Optional

import frappe
from frappe import _
from frappe.utils import cint, getdate, nowdate, today

from superadmin import audit


def get_plan(plan_name: str):
	if not plan_name or not frappe.db.exists("SaaS Plan", plan_name):
		return None
	return frappe.get_doc("SaaS Plan", plan_name)


def get_subscription_for_tenant(tenant_company: str):
	if not tenant_company:
		return None
	name = frappe.db.get_value("SaaS Subscription", {"tenant_company": tenant_company}, "name")
	if not name:
		return None
	return frappe.get_doc("SaaS Subscription", name)


def get_limits_from_plan(plan_doc) -> dict:
	from superadmin.entitlements import plan_enabled_modules, plan_install_app_names

	features = []
	for row in plan_doc.get("features") or []:
		features.append(
			{
				"key": row.feature_key,
				"label": row.feature_label,
				"enabled": cint(row.enabled),
				"limit_value": row.limit_value,
			}
		)
	return {
		"max_users": plan_doc.max_users,
		"max_companies": plan_doc.max_companies or 1,
		"max_branches": cint(getattr(plan_doc, "max_branches", None) or 0) or 1,
		"max_storage_mb": plan_doc.max_storage_mb,
		"max_api_requests": cint(getattr(plan_doc, "max_api_requests", None) or 0),
		"install_apps": "\n".join(plan_install_app_names(plan_doc)),
		"allowed_modules": plan_enabled_modules(plan_doc),
		"features": features,
		"plan_code": plan_doc.name,
		"price_monthly": getattr(plan_doc, "price_monthly", None) or plan_doc.price,
		"price_yearly": getattr(plan_doc, "price_yearly", None),
		"support_level": getattr(plan_doc, "support_level", None),
		"backup_included": cint(getattr(plan_doc, "backup_included", 1)),
	}


def _write_site_config_keys(site_name: str, payload: dict) -> None:
	import os

	from frappe.installer import update_site_config
	from frappe.utils import get_bench_path

	site_name = (site_name or "").strip()
	if not site_name:
		return
	config_path = os.path.join(get_bench_path(), "sites", site_name, "site_config.json")
	if not os.path.isfile(config_path):
		frappe.throw(_("Site config not found for {0}").format(site_name))
	for key, value in payload.items():
		update_site_config(key, value, site_config_path=config_path)


def apply_limits_to_site(site_name: str, limits: dict) -> None:
	"""Push plan limits into tenant site_config.json and apply module/app entitlements."""
	site_name = (site_name or "").strip()
	if not site_name:
		return

	payload = {
		"superadmin_max_users": limits.get("max_users"),
		"superadmin_max_companies": limits.get("max_companies"),
		"superadmin_max_branches": limits.get("max_branches"),
		"superadmin_max_storage_mb": limits.get("max_storage_mb"),
		"superadmin_max_api_requests": limits.get("max_api_requests"),
		"superadmin_plan": limits.get("plan_code") or limits.get("plan"),
		"superadmin_features": json.dumps(limits.get("features") or [], ensure_ascii=False),
		"superadmin_allowed_modules": json.dumps(limits.get("allowed_modules") or [], ensure_ascii=False),
	}
	_write_site_config_keys(site_name, payload)

	# Full entitlements (Module Profile + roles) when plan doc available
	plan_code = limits.get("plan_code") or limits.get("plan")
	if plan_code and frappe.db.exists("SaaS Plan", plan_code):
		from superadmin.entitlements import apply_entitlements_to_site

		apply_entitlements_to_site(site_name, frappe.get_doc("SaaS Plan", plan_code))


def suspend_tenant(tenant_company: str, reason: str = "") -> None:
	"""Put tenant in maintenance without whitelist checks (internal / scheduler)."""
	from superadmin.tenant_access import (
		_append_log,
		_run_set_maintenance_mode,
		_set_company_suspended_marker,
		_site_exists,
	)

	if not frappe.db.exists("Tenant Company", tenant_company):
		return
	doc = frappe.get_doc("Tenant Company", tenant_company)
	if doc.status != "Active":
		return
	site_name = (doc.site_name or "").strip()
	if not site_name or not _site_exists(site_name):
		return
	if (doc.company_access or "Active") == "Suspended":
		return
	try:
		log = _run_set_maintenance_mode(site_name, turn_on=True)
		_set_company_suspended_marker(site_name, True)
		doc.reload()
		doc.company_access = "Suspended"
		if reason:
			doc.provision_log = _append_log(doc.provision_log, _("Suspended: {0}\n{1}").format(reason, log[-4000:]))
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		audit.log_action("tenant_suspended", "Tenant Company", tenant_company, reason or "")
	except Exception:
		frappe.log_error(title="superadmin suspend_tenant")


def activate_tenant(tenant_company: str, reason: str = "") -> None:
	from superadmin.tenant_access import (
		_append_log,
		_run_set_maintenance_mode,
		_set_company_suspended_marker,
		_site_exists,
	)

	if not frappe.db.exists("Tenant Company", tenant_company):
		return
	doc = frappe.get_doc("Tenant Company", tenant_company)
	if doc.status != "Active":
		return
	site_name = (doc.site_name or "").strip()
	if not site_name or not _site_exists(site_name):
		return
	if (doc.company_access or "Active") == "Active":
		return
	try:
		log = _run_set_maintenance_mode(site_name, turn_on=False)
		_set_company_suspended_marker(site_name, False)
		doc.reload()
		doc.company_access = "Active"
		if reason:
			doc.provision_log = _append_log(doc.provision_log, _("Activated: {0}\n{1}").format(reason, log[-4000:]))
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		audit.log_action("tenant_activated", "Tenant Company", tenant_company, reason or "")
	except Exception:
		frappe.log_error(title="superadmin activate_tenant")


def _plan_grace_days(sub) -> int:
	plan = sub.plan
	if not plan:
		return 3
	return cint(frappe.db.get_value("SaaS Plan", plan, "grace_days")) or 3


def enforce_subscription_row(sub) -> Optional[str]:
	"""Apply suspend/activate rules; return new status if changed."""
	if isinstance(sub, str):
		sub = frappe.get_doc("SaaS Subscription", sub)
	prev_status = sub.status or "Trial"
	today_d = getdate(today())
	new_status = prev_status
	tenant = sub.tenant_company

	if prev_status in ("Expired", "Cancelled", "Suspended"):
		suspend_tenant(tenant, _("Subscription status: {0}").format(prev_status))
		return None

	if prev_status in ("Active", "Trial", "Grace"):
		if prev_status == "Trial" and sub.trial_end and getdate(sub.trial_end) < today_d:
			new_status = "Expired"
		elif prev_status == "Active" and sub.current_period_end and getdate(sub.current_period_end) < today_d:
			grace_days = _plan_grace_days(sub)
			grace_until = sub.grace_until or sub.current_period_end
			if grace_until and getdate(grace_until) >= today_d:
				new_status = "Grace"
			else:
				new_status = "Past Due"
				sub.grace_until = getdate(sub.current_period_end)
				if grace_days:
					from frappe.utils import add_days

					sub.grace_until = add_days(getdate(sub.current_period_end), grace_days)
		elif prev_status == "Grace" and sub.grace_until and getdate(sub.grace_until) < today_d:
			new_status = "Past Due"

	if prev_status == "Past Due":
		grace_until = sub.grace_until
		if not grace_until:
			grace_days = _plan_grace_days(sub)
			from frappe.utils import add_days

			base = sub.current_period_end or sub.next_billing_date or today_d
			grace_until = add_days(getdate(base), grace_days)
			sub.grace_until = grace_until
		if grace_until and getdate(grace_until) < today_d:
			new_status = "Suspended"
			suspend_tenant(tenant, _("Past due beyond grace"))
		else:
			activate_tenant(tenant, _("Grace period"))

	if new_status in ("Expired", "Suspended") and new_status != prev_status:
		suspend_tenant(tenant, _("Subscription → {0}").format(new_status))

	if new_status in ("Active", "Trial", "Grace") and prev_status in ("Suspended", "Past Due"):
		activate_tenant(tenant, _("Subscription → {0}").format(new_status))

	if new_status != prev_status:
		sub.status = new_status
		sub.save(ignore_permissions=True)
		frappe.db.commit()
		_notify_status_change(sub, prev_status, new_status)
		return new_status
	return None


def _notify_status_change(sub, old_status: str, new_status: str) -> None:
	from superadmin import notifications

	ctx = {
		"subscription": sub.name,
		"tenant_company": sub.tenant_company,
		"old_status": old_status,
		"new_status": new_status,
		"billing_email": sub.billing_email,
	}
	if new_status == "Expired":
		notifications.notify_event("subscription_expired", ctx)
	elif new_status == "Trial" and sub.trial_end:
		notifications.notify_event("subscription_trial_ending", ctx)
	elif new_status == "Suspended":
		notifications.notify_event("subscription_expired", ctx)


def enforce_all_subscriptions() -> None:
	"""Hourly: transition subscriptions and suspend tenants when needed."""
	names = frappe.get_all("SaaS Subscription", pluck="name", order_by="modified asc")
	for name in names:
		try:
			sub = frappe.get_doc("SaaS Subscription", name)
			enforce_subscription_row(sub)
			_enforce_user_limit(sub)
		except Exception:
			frappe.log_error(title=f"superadmin enforce subscription {name}")


def _enforce_user_limit(sub) -> None:
	"""Disable excess enabled users on tenant when over plan max_users."""
	plan = get_plan(sub.plan)
	if not plan or not plan.max_users:
		return
	tc = frappe.db.get_value(
		"Tenant Company",
		sub.tenant_company,
		["site_name", "name"],
		as_dict=True,
	)
	if not tc or not tc.site_name:
		return
	from superadmin.compat import with_site

	max_users = cint(plan.max_users)

	def _inner():
		users = frappe.get_all(
			"User",
			filters={
				"enabled": 1,
				"user_type": "System User",
				"name": ["not in", ["Administrator", "Guest"]],
			},
			pluck="name",
			order_by="creation asc",
		)
		if len(users) <= max_users:
			return
		for user in users[max_users:]:
			try:
				frappe.db.set_value("User", user, "enabled", 0)
			except Exception:
				pass
		frappe.db.commit()
		from superadmin import notifications

		notifications.notify_event(
			"limit_exceeded",
			{
				"tenant_company": tc.name,
				"site_name": tc.site_name,
				"limit": "max_users",
				"max": max_users,
				"billing_email": sub.billing_email,
			},
		)

	try:
		with_site(tc.site_name, _inner)
	except Exception:
		frappe.log_error(title=f"superadmin user limit {tc.site_name}")
