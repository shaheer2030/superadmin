"""Platform operations health snapshot."""

from __future__ import annotations

import os
import shutil

import frappe
from frappe.utils import get_bench_path

from superadmin.permissions import only_platform


def _ssl_pending_count() -> int:
	queue = os.path.join(get_bench_path(), "apps", "superadmin", "ssl-queue")
	if not os.path.isdir(queue):
		return 0
	try:
		return len([f for f in os.listdir(queue) if f.endswith(".req")])
	except OSError:
		return 0


def _sites_disk_usage() -> int:
	sites = os.path.join(get_bench_path(), "sites")
	total = 0
	try:
		for entry in os.scandir(sites):
			if entry.is_dir(follow_symlinks=False):
				for root, _dirs, files in os.walk(entry.path):
					for f in files:
						try:
							total += os.path.getsize(os.path.join(root, f))
						except OSError:
							pass
	except OSError:
		pass
	return total


@frappe.whitelist()
def get_platform_health():
	only_platform("Platform Ops", "Platform Admin")

	tenant_status = frappe.db.sql(
		"""
		SELECT status, COUNT(*) AS cnt
		FROM `tabTenant Company`
		GROUP BY status
		""",
		as_dict=True,
	)
	sub_status = frappe.db.sql(
		"""
		SELECT status, COUNT(*) AS cnt
		FROM `tabSaaS Subscription`
		GROUP BY status
		""",
		as_dict=True,
	)

	failed_backups = frappe.get_all(
		"Tenant Backup Job",
		filters={"status": "Failed"},
		fields=["name", "site_name", "modified"],
		order_by="modified desc",
		limit=10,
	)
	failed_provisions = frappe.get_all(
		"Tenant Company",
		filters={"status": "Failed"},
		fields=["name", "site_name", "modified"],
		order_by="modified desc",
		limit=10,
	)

	disk = _sites_disk_usage()
	return {
		"tenant_counts": {r.status: r.cnt for r in tenant_status},
		"subscription_counts": {r.status: r.cnt for r in sub_status},
		"sites_disk_bytes": disk,
		"bench_disk_free_bytes": shutil.disk_usage(get_bench_path()).free,
		"ssl_queue_pending": _ssl_pending_count(),
		"recent_failed_backups": failed_backups,
		"recent_failed_provisions": failed_provisions,
	}