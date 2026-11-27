"""Guest / customer portal APIs."""

from __future__ import annotations

from typing import Optional

import frappe
from frappe import _
from frappe.utils import validate_email_address

from superadmin.rate_limit import assert_rate_limit


def _normalize_email(email: str) -> str:
	email = (email or "").strip().lower()
	validate_email_address(email, throw=True)
	return email


def _tenant_for_email(email: str) -> Optional[dict]:
	row = frappe.db.get_value(
		"Tenant Company",
		{"admin_email": email},
		["name", "company_name", "site_name", "status", "company_access", "subscription", "plan"],
		as_dict=True,
	)
	return row


@frappe.whitelist(allow_guest=True)
def get_public_plans():
	plans = frappe.get_all(
		"SaaS Plan",
		filters={"is_active": 1, "is_public": 1},
		fields=[
			"name",
			"plan_code",
			"plan_name",
			"description",
			"price",
			"price_monthly",
			"price_yearly",
			"currency",
			"billing_period",
			"is_free",
			"trial_days",
			"max_users",
			"max_companies",
			"max_branches",
			"max_storage_mb",
			"support_level",
			"backup_included",
			"sort_order",
		],
		order_by="sort_order asc, price asc",
	)
	out = []
	for p in plans:
		doc = frappe.get_doc("SaaS Plan", p.name)
		apps = [
			{"app_name": r.app_name, "app_label": r.app_label or r.app_name}
			for r in (doc.plan_apps or [])
			if r.install
		]
		modules = [
			{"module_name": r.module_name, "module_label": r.module_label or r.module_name}
			for r in (doc.plan_modules or [])
			if r.enabled
		]
		features = [
			{"key": r.feature_key, "label": r.feature_label or r.feature_key}
			for r in (doc.features or [])
			if r.enabled
		]
		row = dict(p)
		row["apps"] = apps
		row["modules"] = modules
		row["feature_list"] = features
		row["price_display"] = p.price_monthly or p.price
		out.append(row)
	return out


@frappe.whitelist(allow_guest=True)
def get_portal_content():
	try:
		pc = frappe.get_single("Portal Content")
		return {
			"hero_title": pc.hero_title,
			"hero_subtitle": pc.hero_subtitle,
			"hero_cta_label": pc.hero_cta_label,
			"features_html": pc.features_html,
			"faq_html": pc.faq_html,
			"contact_email": pc.contact_email,
			"contact_phone": pc.contact_phone,
			"footer_html": pc.footer_html,
			"show_plans_section": pc.show_plans_section,
		}
	except Exception:
		return {}


@frappe.whitelist(allow_guest=True)
def get_customer_dashboard(email: Optional[str] = None):
	assert_rate_limit(f"portal_dashboard:{email or 'anon'}", limit=12, window_seconds=600)
	email = _normalize_email(email or "")
	tc = _tenant_for_email(email)
	if not tc:
		frappe.throw(_("No account found for this email."))

	sub = None
	if tc.subscription and frappe.db.exists("SaaS Subscription", tc.subscription):
		sub = frappe.db.get_value(
			"SaaS Subscription",
			tc.subscription,
			["name", "plan", "status", "current_period_end", "trial_end", "next_billing_date"],
			as_dict=True,
		)

	invoices = frappe.get_all(
		"SaaS Invoice",
		filters={"tenant_company": tc.name},
		fields=["name", "amount", "currency", "status", "due_date", "paid_on"],
		order_by="creation desc",
		limit=20,
	)

	tickets = frappe.get_all(
		"Platform Support Ticket",
		filters={"tenant_company": tc.name, "raised_by": email},
		fields=["name", "subject", "status", "priority", "modified"],
		order_by="modified desc",
		limit=20,
	)

	return {
		"tenant_company": tc.name,
		"company_name": tc.company_name,
		"site_name": tc.site_name,
		"site_url": f"https://{tc.site_name}" if tc.site_name else None,
		"access": tc.company_access,
		"status": tc.status,
		"subscription": sub,
		"plan": tc.plan,
		"invoices": invoices,
		"tickets": tickets,
	}


@frappe.whitelist(allow_guest=True)
def create_customer_ticket(
	email: Optional[str] = None,
	subject: Optional[str] = None,
	description: Optional[str] = None,
	priority: str = "Medium",
):
	assert_rate_limit(f"portal_ticket:{email or 'anon'}", limit=6, window_seconds=3600)
	email = _normalize_email(email or "")
	subject = (subject or "").strip()
	description = (description or "").strip()
	if len(subject) < 3:
		frappe.throw(_("Subject is required"))
	tc = _tenant_for_email(email)
	if not tc:
		frappe.throw(_("No account found for this email."))

	tkt = frappe.get_doc(
		{
			"doctype": "Platform Support Ticket",
			"tenant_company": tc.name,
			"raised_by": email,
			"subject": subject,
			"description": description,
			"priority": priority or "Medium",
			"status": "Open",
		}
	)
	tkt.insert(ignore_permissions=True)
	frappe.db.commit()

	from superadmin import notifications

	notifications.notify_event(
		"ticket_created",
		{"ticket": tkt.name, "subject": subject, "tenant_company": tc.name, "billing_email": email},
	)
	return {"ok": True, "ticket": tkt.name}


@frappe.whitelist(allow_guest=True)
def request_customer_invoice_pay(invoice_name: Optional[str] = None, email: Optional[str] = None):
	assert_rate_limit(f"portal_pay:{email or 'anon'}", limit=10, window_seconds=600)
	email = _normalize_email(email or "")
	invoice_name = (invoice_name or "").strip()
	if not frappe.db.exists("SaaS Invoice", invoice_name):
		frappe.throw(_("Invoice not found"))

	inv = frappe.get_doc("SaaS Invoice", invoice_name)
	tc = _tenant_for_email(email)
	if not tc or inv.tenant_company != tc.name:
		frappe.throw(_("Invoice not found"))

	instructions = frappe.db.get_single_value("Superadmin Settings", "payment_instructions") or ""
	if not instructions:
		instructions = _(
			"Contact billing to complete payment for invoice {0} ({1} {2})."
		).format(inv.name, inv.amount, inv.currency)
	return {"ok": True, "invoice": inv.name, "amount": inv.amount, "currency": inv.currency, "instructions": instructions}