"""Platform role helpers for Superadmin SaaS layer."""

from __future__ import annotations

import frappe

PLATFORM_ROLES = ["Platform Admin", "Platform Billing", "Platform Support", "Platform Ops"]


def ensure_platform_roles():
	"""Create platform roles if they do not exist."""
	for role_name in PLATFORM_ROLES:
		if frappe.db.exists("Role", role_name):
			continue
		role = frappe.new_doc("Role")
		role.role_name = role_name
		role.desk_access = 1
		role.insert(ignore_permissions=True)


def only_platform(*roles):
	"""Restrict to given platform roles plus System Manager."""
	allowed = list(roles) + ["System Manager"]
	frappe.only_for(allowed)
