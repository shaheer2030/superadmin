"""Create and manage SaaS subscriptions."""

from __future__ import annotations

from typing import Optional

import frappe
from frappe import _
from frappe.utils import add_days, add_months, add_years, getdate, today

from superadmin import audit
from superadmin.limits import apply_limits_to_site, get_limits_from_plan, get_plan


def _period_end(start, billing_period: str):
	if billing_period == "Yearly":
		return add_years(start, 1)
	if billing_period == "Monthly":
		return add_months(start, 1)
	if billing_period == "Trial":
		return start
	return add_months(start, 1)


@frappe.whitelist()
def create_subscription_for_tenant(
	tenant_company: str,
	plan_code: str,
	billing_email: Optional[str] = None,
	coupon: Optional[str] = None,
) -> str:
	# Allow System Manager / Administrator / RQ jobs; otherwise platform billing roles
	user = frappe.session.user
	if user not in ("Administrator", "Guest") and "System Manager" not in frappe.get_roles():
		from superadmin.permissions import only_platform
		only_platform("Platform Admin", "Platform Billing")

	if frappe.db.exists("SaaS Subscription", {"tenant_company": tenant_company}):
		frappe.throw(_("Tenant already has a subscription"))

	plan = get_plan(plan_code)
	if not plan:
		frappe.throw(_("Plan not found: {0}").format(plan_code))

	tc = frappe.get_doc("Tenant Company", tenant_company)
	start = getdate(today())
	status = "Trial" if (plan.is_free or plan.trial_days) else "Active"
	trial_end = None
	period_start = start
	period_end = _period_end(start, plan.billing_period or "Monthly")

	if status == "Trial":
		days = int(plan.trial_days or 14)
		trial_end = add_days(start, days)
		period_end = trial_end

	sub = frappe.get_doc(
		{
			"doctype": "SaaS Subscription",
			"tenant_company": tenant_company,
			"plan": plan.name,
			"status": status,
			"start_date": start,
			"trial_end": trial_end,
			"current_period_start": period_start,
			"current_period_end": period_end,
			"next_billing_date": period_end,
			"billing_email": billing_email or tc.admin_email,
			"coupon": coupon,
		}
	)
	sub.insert(ignore_permissions=True)

	tc.subscription = sub.name
	tc.plan = plan.name
	tc.save(ignore_permissions=True)

	site = (tc.site_name or "").strip()
	if site:
		limits = get_limits_from_plan(plan)
		try:
			from superadmin.entitlements import ensure_missing_apps_installed
			from superadmin.tenant_access import _site_exists

			if _site_exists(site):
				ensure_missing_apps_installed(site, plan)
				apply_limits_to_site(site, limits)
		except Exception:
			frappe.log_error(title="superadmin apply_limits on subscribe")

	frappe.db.commit()
	audit.log_action("subscription_created", "SaaS Subscription", sub.name, plan_code)
	return sub.name


@frappe.whitelist()
def change_plan(subscription_name: str, new_plan_code: str) -> None:
	from superadmin.permissions import only_platform

	only_platform("Platform Admin", "Platform Billing")
	sub = frappe.get_doc("SaaS Subscription", subscription_name)
	old_plan = sub.plan
	plan = get_plan(new_plan_code)
	if not plan:
		frappe.throw(_("Plan not found"))

	sub.plan = plan.name
	sub.notes = (sub.notes or "") + f"\n{_('Plan changed')} {old_plan} → {plan.name}"
	sub.save(ignore_permissions=True)

	tc = frappe.get_doc("Tenant Company", sub.tenant_company)
	tc.plan = plan.name
	tc.save(ignore_permissions=True)

	site = (tc.site_name or "").strip()
	if site:
		try:
			from superadmin.entitlements import ensure_missing_apps_installed

			ensure_missing_apps_installed(site, plan)
			apply_limits_to_site(site, get_limits_from_plan(plan))
		except Exception:
			frappe.log_error(title="superadmin apply_limits change_plan")

	frappe.db.commit()
	audit.log_action("subscription_plan_change", "SaaS Subscription", subscription_name, new_plan_code)


@frappe.whitelist()
def cancel_subscription(subscription_name: str, at_period_end: bool = True) -> None:
	from superadmin.permissions import only_platform

	only_platform("Platform Admin", "Platform Billing")
	sub = frappe.get_doc("SaaS Subscription", subscription_name)
	sub.cancel_at_period_end = 1 if at_period_end else 0
	if not at_period_end:
		sub.status = "Cancelled"
		sub.cancelled_on = today()
		from superadmin.limits import suspend_tenant

		suspend_tenant(sub.tenant_company, _("Subscription cancelled"))
	else:
		sub.notes = (sub.notes or "") + f"\n{_('Cancel scheduled at period end')}"
	sub.save(ignore_permissions=True)
	frappe.db.commit()
	audit.log_action("subscription_cancel", "SaaS Subscription", subscription_name, str(at_period_end))