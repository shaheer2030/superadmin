"""Script report — SaaS platform metrics."""

from __future__ import annotations

import frappe
from frappe import _


def execute(filters=None):
	from superadmin.analytics import get_saas_dashboard_metrics

	m = get_saas_dashboard_metrics()
	columns = [
		{"label": _("Metric"), "fieldname": "metric", "fieldtype": "Data", "width": 240},
		{"label": _("Value"), "fieldname": "value", "fieldtype": "Data", "width": 200},
	]
	data = [
		{"metric": _("Active tenants"), "value": m["tenants_active"]},
		{"metric": _("Suspended tenants"), "value": m["tenants_suspended"]},
		{"metric": _("Open support tickets"), "value": m["tickets_open"]},
		{"metric": _("Unpaid invoices total (SAR)"), "value": m["unpaid_invoices_total"]},
		{"metric": _("Backups 7d success"), "value": m["backups_7d_success"]},
		{"metric": _("Backups 7d failed"), "value": m["backups_7d_failed"]},
		{"metric": _("Generated at"), "value": m["generated_at"]},
	]
	for status, cnt in sorted((m.get("subscriptions_by_status") or {}).items()):
		data.insert(2, {"metric": _("Subscriptions — {0}").format(_(status)), "value": cnt})
	return columns, data
