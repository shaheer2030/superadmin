"""Time-limited, audited technical access grants to tenant environments."""

from __future__ import annotations

from typing import Optional

import frappe
from frappe import _
from frappe.utils import add_to_date, now_datetime

from superadmin import audit
from superadmin.permissions import only_platform


@frappe.whitelist()
def grant_technical_access(
	tenant_company: str,
	hours: int = 4,
	reason: Optional[str] = None,
):
	"""Record an approved temporary support access window (audit only; no free shell)."""
	only_platform("Platform Admin", "Platform Support", "Platform Ops")
	if not frappe.db.exists("Tenant Company", tenant_company):
		frappe.throw(_("Tenant Company not found"))
	hours = max(1, min(int(hours or 4), 72))
	reason = (reason or "").strip() or _("Support investigation")
	expires = add_to_date(now_datetime(), hours=hours)
	detail = f"hours={hours}; expires={expires}; reason={reason}"
	audit.log_action("technical_access_grant", "Tenant Company", tenant_company, detail)
	return {
		"ok": True,
		"tenant_company": tenant_company,
		"expires_on": str(expires),
		"hours": hours,
		"message": _("Access grant recorded. Use Desk Impersonation / site login only within the approved window."),
	}


@frappe.whitelist()
def revoke_technical_access(tenant_company: str, reason: Optional[str] = None):
	only_platform("Platform Admin", "Platform Support", "Platform Ops")
	audit.log_action(
		"technical_access_revoke",
		"Tenant Company",
		tenant_company,
		(reason or "").strip() or _("Revoked"),
	)
	return {"ok": True}
