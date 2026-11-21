"""Install/migrate helpers for public portal."""

from __future__ import annotations

import frappe


def ensure_portal_home():
	"""Point Website Settings home page to Superadmin landing for guests."""
	try:
		ws = frappe.get_single("Website Settings")
		# Prefer explicit home route provided by www/home.html
		if (ws.home_page or "").strip() in ("", "login", "me"):
			ws.home_page = "home"
			ws.save(ignore_permissions=True)
			frappe.db.commit()
	except Exception:
		frappe.log_error(title="superadmin ensure_portal_home")
