"""SaaS dashboard metrics — real counts only."""

from __future__ import annotations

import frappe
from frappe.utils import add_days, now_datetime, today


def get_saas_dashboard_metrics() -> dict:
	tenants_active = frappe.db.count("Tenant Company", {"status": "Active", "company_access": "Active"})
	tenants_suspended = frappe.db.count("Tenant Company", {"status": "Active", "company_access": "Suspended"})

	sub_rows = frappe.db.sql(
		"SELECT status, COUNT(*) FROM `tabSaaS Subscription` GROUP BY status",
		as_dict=False,
	)
	subscriptions_by_status = {row[0]: row[1] for row in sub_rows}

	unpaid_sum = frappe.db.sql(
		"""
		SELECT COALESCE(SUM(amount), 0)
		FROM `tabSaaS Invoice`
		WHERE status = 'Unpaid'
		"""
	)[0][0]

	tickets_open = frappe.db.count(
		"Platform Support Ticket",
		{"status": ["in", ["Open", "In Progress", "Waiting Customer"]]},
	)

	since = add_days(today(), -7)
	backup_success = frappe.db.count(
		"Tenant Backup Job",
		{"status": "Success", "creation": [">=", since]},
	)
	backup_failed = frappe.db.count(
		"Tenant Backup Job",
		{"status": "Failed", "creation": [">=", since]},
	)

	return {
		"tenants_active": tenants_active,
		"tenants_suspended": tenants_suspended,
		"subscriptions_by_status": subscriptions_by_status,
		"unpaid_invoices_total": float(unpaid_sum or 0),
		"tickets_open": tickets_open,
		"backups_7d_success": backup_success,
		"backups_7d_failed": backup_failed,
		"generated_at": str(now_datetime()),
	}