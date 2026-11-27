"""SaaS billing — invoices, coupons, platform company."""

from __future__ import annotations

from typing import Optional, Tuple

import frappe
from frappe import _
from frappe.utils import add_days, add_months, add_years, flt, getdate, now_datetime, today

from superadmin import audit, notifications
from superadmin.limits import activate_tenant, get_plan

PLATFORM_COMPANY = "ORACPC Platform"
PLATFORM_ABBR = "ORAC"


def ensure_platform_company() -> None:
	if not frappe.db.table_exists("tabCompany"):
		return
	if not frappe.db.exists("Company", PLATFORM_COMPANY):
		try:
			company = frappe.get_doc(
				{
					"doctype": "Company",
					"company_name": PLATFORM_COMPANY,
					"abbr": PLATFORM_ABBR,
					"default_currency": "SAR",
					"country": "Saudi Arabia",
				}
			)
			company.insert(ignore_permissions=True)
			frappe.db.commit()
		except Exception:
			frappe.log_error(title="superadmin ensure_platform_company")


def ensure_customer_for_tenant(tenant_company: str) -> Optional[str]:
	if not frappe.db.table_exists("tabCustomer"):
		return None
	tc = frappe.get_doc("Tenant Company", tenant_company)
	name = tc.company_name or tenant_company
	if frappe.db.exists("Customer", name):
		return name
	try:
		cust = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": name,
				"customer_type": "Company",
				"customer_group": frappe.db.get_single_value("Selling Settings", "customer_group") or "All Customer Groups",
				"territory": frappe.db.get_single_value("Selling Settings", "territory") or "All Territories",
			}
		)
		cust.insert(ignore_permissions=True)
		frappe.db.commit()
		return cust.name
	except Exception:
		frappe.log_error(title="superadmin ensure_customer")
		return None


def apply_coupon(amount: float, coupon_code: Optional[str], plan_code: str) -> Tuple[float, Optional[str]]:
	amount = flt(amount)
	if not coupon_code:
		return amount, None
	code = coupon_code.strip()
	if not frappe.db.exists("SaaS Coupon", code):
		frappe.throw(_("Invalid coupon code"))
	coupon = frappe.get_doc("SaaS Coupon", code)
	if not coupon.is_active:
		frappe.throw(_("Coupon is not active"))
	now = now_datetime()
	if coupon.valid_from and now < coupon.valid_from:
		frappe.throw(_("Coupon is not yet valid"))
	if coupon.valid_to and now > coupon.valid_to:
		frappe.throw(_("Coupon has expired"))
	if coupon.max_uses and (coupon.used_count or 0) >= coupon.max_uses:
		frappe.throw(_("Coupon usage limit reached"))
	applicable = (coupon.applicable_plans or "").strip()
	if applicable:
		allowed = {p.strip() for p in applicable.split(",") if p.strip()}
		if plan_code not in allowed:
			frappe.throw(_("Coupon does not apply to this plan"))

	new_amount = amount
	if coupon.discount_type == "Percent":
		pct = flt(coupon.discount_percent)
		new_amount = max(0, amount * (1 - pct / 100.0))
	else:
		new_amount = max(0, amount - flt(coupon.discount_amount))
	return new_amount, coupon.name


def _period_delta(billing_period: str):
	if billing_period == "Yearly":
		return lambda d: add_years(d, 1)
	if billing_period == "Monthly":
		return lambda d: add_months(d, 1)
	return lambda d: add_days(d, 30)


def _vat_amount(net_amount: float) -> Tuple[float, float]:
	"""Return (gross, vat) using Superadmin Settings when VAT enabled."""
	net_amount = flt(net_amount)
	try:
		enabled = frappe.db.get_single_value("Superadmin Settings", "vat_enabled")
		rate = flt(frappe.db.get_single_value("Superadmin Settings", "vat_rate") or 0)
	except Exception:
		return net_amount, 0
	if not enabled or rate <= 0:
		return net_amount, 0
	vat = flt(net_amount * rate / 100.0)
	return flt(net_amount + vat), vat


@frappe.whitelist()
def create_invoice_for_subscription(
	subscription_name: str,
	coupon_code: Optional[str] = None,
) -> str:
	from superadmin.permissions import only_platform

	only_platform("Platform Admin", "Platform Billing")
	sub = frappe.get_doc("SaaS Subscription", subscription_name)
	plan = get_plan(sub.plan)
	if not plan:
		frappe.throw(_("Plan not found"))

	currency = plan.currency or "SAR"
	period = (sub.get("billing_period") if hasattr(sub, "billing_period") else None) or plan.billing_period
	if period == "Yearly" and flt(getattr(plan, "price_yearly", None)):
		amount = flt(plan.price_yearly)
	elif flt(getattr(plan, "price_monthly", None)):
		amount = flt(plan.price_monthly)
	else:
		amount = flt(plan.price)
	coupon_name = None
	if coupon_code:
		amount, coupon_name = apply_coupon(amount, coupon_code, plan.name)
	amount, vat = _vat_amount(amount)

	inv = frappe.get_doc(
		{
			"doctype": "SaaS Invoice",
			"subscription": sub.name,
			"tenant_company": sub.tenant_company,
			"plan": plan.name,
			"amount": amount,
			"currency": currency,
			"status": "Unpaid",
			"due_date": today(),
			"coupon": coupon_name,
			"description": _("Subscription billing for {0}").format(plan.plan_name)
			+ (f" (incl. VAT {vat})" if vat else ""),
		}
	)
	inv.insert(ignore_permissions=True)

	erp_si = None
	if frappe.db.table_exists("tabSales Invoice") and amount > 0:
		try:
			ensure_platform_company()
			customer = ensure_customer_for_tenant(sub.tenant_company)
			if customer:
				si = frappe.get_doc(
					{
						"doctype": "Sales Invoice",
						"company": PLATFORM_COMPANY,
						"customer": customer,
						"currency": currency,
						"due_date": inv.due_date,
						"items": [
							{
								"item_code": plan.plan_name,
								"item_name": plan.plan_name,
								"description": inv.description,
								"qty": 1,
								"rate": amount,
							}
						],
					}
				)
				si.insert(ignore_permissions=True)
				erp_si = si.name
				inv.erpnext_sales_invoice = erp_si
				inv.save(ignore_permissions=True)
		except Exception:
			frappe.log_error(title="superadmin sales invoice")

	frappe.db.commit()
	audit.log_action("invoice_created", "SaaS Invoice", inv.name, subscription_name)
	notifications.notify_event(
		"invoice_created",
		{
			"invoice": inv.name,
			"amount": amount,
			"currency": currency,
			"tenant_company": sub.tenant_company,
			"billing_email": sub.billing_email,
		},
	)
	return inv.name


@frappe.whitelist()
def mark_invoice_paid(invoice_name: str) -> None:
	from superadmin.permissions import only_platform

	only_platform("Platform Admin", "Platform Billing")
	inv = frappe.get_doc("SaaS Invoice", invoice_name)
	if inv.status == "Paid":
		return
	inv.status = "Paid"
	inv.paid_on = now_datetime()
	inv.save(ignore_permissions=True)

	sub = None
	if inv.subscription:
		sub = frappe.get_doc("SaaS Subscription", inv.subscription)
		plan = get_plan(sub.plan)
		advance = _period_delta(plan.billing_period if plan else "Monthly")
		start = getdate(today())
		sub.current_period_start = start
		sub.current_period_end = advance(start)
		sub.next_billing_date = sub.current_period_end
		sub.status = "Active"
		sub.save(ignore_permissions=True)
		if sub.tenant_company:
			tc = frappe.db.get_value(
				"Tenant Company",
				sub.tenant_company,
				["company_access", "name"],
				as_dict=True,
			)
			if tc and tc.company_access == "Suspended":
				activate_tenant(sub.tenant_company, _("Invoice paid"))

	if inv.coupon:
		frappe.db.set_value(
			"SaaS Coupon",
			inv.coupon,
			"used_count",
			(frappe.db.get_value("SaaS Coupon", inv.coupon, "used_count") or 0) + 1,
		)

	frappe.db.commit()
	audit.log_action("invoice_paid", "SaaS Invoice", invoice_name, inv.subscription or "")
	notifications.notify_event(
		"invoice_paid",
		{
			"invoice": inv.name,
			"subscription": inv.subscription,
			"tenant_company": inv.tenant_company,
		},
	)