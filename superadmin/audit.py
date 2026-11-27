"""Append-only platform audit trail."""

from __future__ import annotations

from typing import Optional

import frappe


def log_action(
	action: str,
	target_doctype: Optional[str] = None,
	target_name: Optional[str] = None,
	detail: str = "",
) -> None:
	"""Record a Platform Audit Log entry."""
	ip_address = getattr(getattr(frappe.local, "request", None), "remote_addr", None)
	if not ip_address:
		ip_address = getattr(frappe.local, "request_ip", None)

	frappe.get_doc(
		{
			"doctype": "Platform Audit Log",
			"action": action,
			"actor": frappe.session.user,
			"target_doctype": target_doctype,
			"target_name": target_name,
			"detail": detail or "",
			"ip_address": ip_address,
		}
	).insert(ignore_permissions=True)
