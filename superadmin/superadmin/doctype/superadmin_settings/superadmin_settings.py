# Copyright (c) 2026, Superadmin and contributors
# For license information, please see license.txt

from __future__ import annotations

import re
from typing import Optional

import frappe
from frappe import _
from frappe.model.document import Document

_DOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9\-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9\-]*[a-z0-9])?)+$", re.I)
_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9\-]*[a-z0-9])?$", re.I)

EMAIL_ACCOUNT_NAME = "Superadmin Signup"


class SuperadminSettings(Document):
	def validate(self):
		domain = (self.base_domain or "").strip().lower().rstrip(".")
		if domain.startswith("www."):
			domain = domain[4:]
		self.base_domain = domain
		if not domain or not _DOMAIN_RE.match(domain):
			frappe.throw(_("Base Domain must look like a domain, e.g. oracpc.tech"))

		mode = (self.email_verification_mode or "Optional").strip()
		if mode not in ("Optional", "Mandatory"):
			frappe.throw(_("Invalid Email verification mode"))
		self.email_verification_mode = mode

		if mode == "Mandatory":
			missing = []
			if not (self.smtp_server or "").strip():
				missing.append(_("SMTP Server"))
			if not self.smtp_port:
				missing.append(_("SMTP Port"))
			if not (self.smtp_email or "").strip():
				missing.append(_("SMTP Email"))
			# password may already be stored
			pw = None
			try:
				pw = self.get_password("smtp_password")
			except Exception:
				pw = None
			if not pw and not self.smtp_password:
				missing.append(_("SMTP Password"))
			if missing:
				frappe.throw(
					_("When Email verification is Mandatory, fill: {0}").format(", ".join(missing))
				)

	def on_update(self):
		if (self.email_verification_mode or "") == "Mandatory":
			self.sync_email_account()

	def sync_email_account(self):
		"""Keep a dedicated Email Account for signup verification mail."""
		pw = None
		try:
			pw = self.get_password("smtp_password")
		except Exception:
			pw = None
		if not pw:
			return

		email = (self.smtp_email or "").strip()
		if frappe.db.exists("Email Account", EMAIL_ACCOUNT_NAME):
			acc = frappe.get_doc("Email Account", EMAIL_ACCOUNT_NAME)
		else:
			acc = frappe.new_doc("Email Account")
			acc.email_account_name = EMAIL_ACCOUNT_NAME

		acc.email_id = email
		acc.login_id_is_different = 0
		acc.enable_outgoing = 1
		acc.default_outgoing = 1
		acc.smtp_server = (self.smtp_server or "").strip()
		acc.smtp_port = int(self.smtp_port or 587)
		acc.use_tls = 1 if self.smtp_use_tls else 0
		acc.use_ssl = 1 if getattr(self, "smtp_use_ssl", 0) else 0
		if hasattr(acc, "use_starttls"):
			acc.use_starttls = 1 if self.smtp_use_tls else 0
		acc.password = pw
		acc.awaiting_password = 0
		if hasattr(acc, "auth_method"):
			acc.auth_method = "Basic"
		acc.save(ignore_permissions=True)


def get_settings():
	return frappe.get_single("Superadmin Settings")


def get_default_server_ip() -> str:
	try:
		return (frappe.db.get_single_value("Superadmin Settings", "default_server_ip") or "").strip()
	except Exception:
		return ""


def get_default_install_apps() -> str:
	try:
		return (frappe.db.get_single_value("Superadmin Settings", "default_install_apps") or "").strip()
	except Exception:
		return ""


def get_base_domain() -> str:
	try:
		return (frappe.db.get_single_value("Superadmin Settings", "base_domain") or "").strip().lower().rstrip(".")
	except Exception:
		return ""


def get_email_verification_mode() -> str:
	try:
		return (frappe.db.get_single_value("Superadmin Settings", "email_verification_mode") or "Optional").strip()
	except Exception:
		return "Optional"


def is_email_verification_mandatory() -> bool:
	return get_email_verification_mode() == "Mandatory"


def expand_site_name(site_name: str, base_domain: Optional[str] = None) -> str:
	raw = (site_name or "").strip().lower().rstrip(".")
	if not raw:
		return raw
	domain = (base_domain if base_domain is not None else get_base_domain()).strip().lower().rstrip(".")
	if "." in raw:
		return raw
	if not domain:
		frappe.throw(_("Set Base Domain in Superadmin Settings before using a short Site Name like {0}.").format(raw))
	if not _LABEL_RE.match(raw):
		frappe.throw(_("Site Name label must be letters/digits/hyphens only, e.g. alnoor (got {0})").format(raw))
	if raw in ("www", "mail", "ftp"):
		frappe.throw(_("Site Name '{0}' is reserved.").format(raw))
	return f"{raw}.{domain}"


def suggest_site_label(company_name: str) -> str:
	"""ASCII slug from company name; empty if not enough latin characters."""
	import unicodedata

	raw = unicodedata.normalize("NFKD", company_name or "")
	raw = raw.encode("ascii", "ignore").decode("ascii")
	label = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
	label = re.sub(r"-{2,}", "-", label)
	if len(label) < 3:
		return ""
	return label[:40]
