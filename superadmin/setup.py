"""Install/migrate helpers for public portal and branding menu."""

from __future__ import annotations

import frappe


def ensure_portal_home():
	"""Point Website Settings home page to Superadmin landing for guests."""
	try:
		ws = frappe.get_single("Website Settings")
		if (ws.home_page or "").strip() in ("", "login", "me"):
			ws.home_page = "home"
			ws.save(ignore_permissions=True)
			frappe.db.commit()
	except Exception:
		frappe.log_error(title="superadmin ensure_portal_home")


def ensure_system_branding_sidebar():
	"""Ensure Superadmin sidebar contains System Branding under Settings."""
	try:
		if not frappe.db.exists("Sidebar", "Superadmin"):
			return
		sidebar = frappe.get_doc("Sidebar", "Superadmin")
		exists = any((row.link_to == "System Branding") for row in (sidebar.items or []))
		if exists:
			# Keep Arabic label consistent
			for row in sidebar.items:
				if row.link_to == "System Branding":
					row.label = "اعدادات النظام والحقوق"
			sidebar.save(ignore_permissions=True)
			frappe.db.commit()
			return

		# Insert after Settings / Superadmin Settings
		insert_at = len(sidebar.items or [])
		for i, row in enumerate(sidebar.items or []):
			if row.link_to == "Superadmin Settings" or (row.label or "") in ("Settings", "إعدادات"):
				insert_at = i + 1
				break

		sidebar.append(
			"items",
			{
				"type": "Link",
				"label": "اعدادات النظام والحقوق",
				"link_type": "DocType",
				"link_to": "System Branding",
				"icon": "image",
				"idx": insert_at + 1,
			},
		)
		# Reorder roughly: move last appended into position by rebuilding
		items = list(sidebar.items)
		new_row = items.pop()
		items.insert(insert_at, new_row)
		sidebar.set("items", [])
		for row in items:
			sidebar.append(
				"items",
				{
					"type": row.type,
					"label": row.label,
					"link_type": getattr(row, "link_type", None),
					"link_to": getattr(row, "link_to", None),
					"icon": getattr(row, "icon", None),
					"hidden": getattr(row, "hidden", 0),
				},
			)
		sidebar.save(ignore_permissions=True)
		frappe.db.commit()
	except Exception:
		frappe.log_error(title="superadmin ensure_system_branding_sidebar")
