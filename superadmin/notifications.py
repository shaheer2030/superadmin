"""Platform email notifications — never raises to callers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import frappe
from frappe import _

from superadmin.superadmin.doctype.superadmin_settings.superadmin_settings import EMAIL_ACCOUNT_NAME

EVENT_SUBJECTS = {
	"signup_received": _("New company signup"),
	"provision_failed": _("Tenant provisioning failed"),
	"subscription_trial_ending": _("Trial ending soon"),
	"subscription_expired": _("Subscription expired or suspended"),
	"invoice_created": _("New SaaS invoice"),
	"invoice_paid": _("Invoice paid — thank you"),
	"backup_failed": _("Tenant backup failed"),
	"ticket_created": _("Support ticket created"),
	"ticket_resolved": _("Support ticket resolved"),
	"limit_exceeded": _("Plan limit exceeded"),
}


def _render_body(event_key: str, context: Dict[str, Any]) -> str:
	lines = [f"<p><b>{frappe.utils.escape_html(EVENT_SUBJECTS.get(event_key, event_key))}</b></p>"]
	for key, val in (context or {}).items():
		if val is None or val == "":
			continue
		lines.append(f"<p><b>{frappe.utils.escape_html(str(key))}:</b> {frappe.utils.escape_html(str(val))}</p>")
	return "\n".join(lines)


def _default_recipients(context: Dict[str, Any]) -> List[str]:
	out = []
	email = (context or {}).get("billing_email") or (context or {}).get("admin_email")
	if email:
		out.append(email.strip().lower())
	ops = frappe.get_all(
		"Has Role",
		filters={"role": ["in", ["Platform Admin", "Platform Ops", "System Manager"]], "parenttype": "User"},
		pluck="parent",
	)
	for user in ops[:20]:
		addr = frappe.db.get_value("User", user, "email")
		if addr and addr not in out:
			out.append(addr)
	return out


def _outgoing_email_account() -> Optional[str]:
	"""Return an Email Account name usable for outgoing mail, or None."""
	if frappe.db.exists("Email Account", EMAIL_ACCOUNT_NAME):
		enabled = frappe.db.get_value("Email Account", EMAIL_ACCOUNT_NAME, "enable_outgoing")
		if enabled:
			return EMAIL_ACCOUNT_NAME
	default = frappe.db.get_value(
		"Email Account",
		{"enable_outgoing": 1, "default_outgoing": 1},
		"name",
	)
	return default


def notify_event(
	event_key: str,
	context: Optional[Dict[str, Any]] = None,
	recipients: Optional[List[str]] = None,
) -> None:
	"""Best-effort platform email. Never surfaces errors to the HTTP caller (e.g. public signup)."""
	try:
		context = dict(context or {})
		subject = EVENT_SUBJECTS.get(event_key) or event_key
		message = _render_body(event_key, context)
		to = list(recipients or []) or _default_recipients(context)
		to = [e for e in to if e]
		if not to:
			return
		account = _outgoing_email_account()
		if not account:
			# No SMTP yet — skip quietly (signup must not show Tools > Email Account).
			return
		kwargs = {
			"recipients": to,
			"subject": subject,
			"message": message,
			"now": True,
			"email_account": account,
		}
		frappe.sendmail(**kwargs)
	except Exception:
		frappe.clear_messages()
		frappe.log_error(title=f"superadmin notify_event {event_key}")