"""Public signup + email verification + login redirect for Superadmin portal."""

from __future__ import annotations

from typing import Optional

import re
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import get_url, now_datetime, validate_email_address

from superadmin.superadmin.doctype.superadmin_settings.superadmin_settings import (
	EMAIL_ACCOUNT_NAME,
	expand_site_name,
	get_base_domain,
	get_default_install_apps,
	get_default_server_ip,
	is_email_verification_mandatory,
	suggest_site_label,
)

TOKEN_HOURS = 24


def _append_log(existing: Optional[str], text: str) -> str:
	return ((existing or "").rstrip() + "\n" + text.strip()).strip()[-65000:]


def _normalize_email(email: str) -> str:
	email = (email or "").strip().lower()
	validate_email_address(email, throw=True)
	return email


def _assert_email_available(email: str, ignore_signup: Optional[str] = None) -> None:
	filters = {"admin_email": email}
	if ignore_signup:
		filters["name"] = ["!=", ignore_signup]
	if frappe.db.exists("Tenant Signup", filters):
		# allow resend only for pending same email handled elsewhere
		existing = frappe.db.get_value(
			"Tenant Signup",
			{"admin_email": email},
			["name", "status"],
			as_dict=True,
		)
		if existing and existing.status in ("Pending Verification",):
			if ignore_signup and existing.name == ignore_signup:
				return
			if not ignore_signup:
				frappe.throw(_("An unverified signup already exists for this email. Check your inbox or wait and retry."))
		elif existing and existing.status in ("Verified", "Provisioning", "Active"):
			frappe.throw(_("This email is already registered."))
	if frappe.db.exists("Tenant Company", {"admin_email": email}):
		frappe.throw(_("This email is already linked to a company account."))


def _assert_site_available(site_name: str) -> None:
	if frappe.db.exists("Tenant Company", {"site_name": site_name}):
		frappe.throw(_("Site Name {0} is already taken.").format(site_name))
	if frappe.db.exists("Tenant Signup", {"site_name": site_name, "status": ["in", ["Pending Verification", "Verified", "Provisioning", "Active"]]}):
		frappe.throw(_("Site Name {0} is already reserved.").format(site_name))
	from frappe.utils import get_bench_path
	import os

	if os.path.isdir(os.path.join(get_bench_path(), "sites", site_name)):
		frappe.throw(_("Site folder {0} already exists on the server.").format(site_name))


def _create_tenant_company_from_signup(signup) -> str:
	server_ip = get_default_server_ip()
	if not server_ip:
		frappe.throw(_("Default Server IP is not set in Superadmin Settings."))
	install_apps = get_default_install_apps() or "erpnext"
	password = signup.get_password("admin_password")
	if not password:
		frappe.throw(_("Administrator Password is missing."))

	doc = frappe.get_doc(
		{
			"doctype": "Tenant Company",
			"company_name": signup.company_name,
			"site_name": signup.site_name,
			"server_ip": server_ip,
			"admin_email": signup.admin_email,
			"admin_password": password,
			"install_apps": install_apps,
			"status": "Draft",
		}
	)
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return doc.name


def _enqueue_provision(docname: str) -> dict:
	from superadmin.api import _validate_site_name, _apps_to_install, _validate_apps_on_bench

	doc = frappe.get_doc("Tenant Company", docname)
	if doc.status == "Active":
		return {"status": "active"}
	if doc.status in ("Queued", "Provisioning"):
		return {"status": "already_queued"}

	_validate_site_name(doc.site_name)
	admin_pw = doc.get_password("admin_password")
	if not admin_pw:
		frappe.throw(_("Set Administrator Password before creating the site."))
	apps_to_install = _apps_to_install(doc)
	_validate_apps_on_bench(apps_to_install)

	doc.status = "Queued"
	doc.progress_percent = 5
	doc.progress_stage = _("Queued")
	doc.provision_log = _("Queued from public signup.")
	doc.save(ignore_permissions=True)
	frappe.db.commit()

	enqueue_kwargs = {
		"queue": "long",
		"timeout": 7200,
		"job_name": f"superadmin-provision-{docname}",
		"docname": docname,
	}
	try:
		job = frappe.enqueue(
			"superadmin.api._provision_job",
			job_id=f"superadmin-provision-{docname}-{frappe.generate_hash(length=8)}",
			**enqueue_kwargs,
		)
	except TypeError:
		job = frappe.enqueue("superadmin.api._provision_job", **enqueue_kwargs)

	job_id = getattr(job, "id", None) or str(job)
	doc.reload()
	doc.provision_log = (doc.provision_log or "") + f"\nRQ job queued: {job_id}"
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"status": "queued", "job_id": job_id, "tenant_company": docname}


def _send_verification_email(signup) -> None:
	token = signup.verification_token
	link = get_url(f"/verify?token={token}")
	subject = _("Confirm your email to create your company account")
	from_name = frappe.db.get_single_value("Superadmin Settings", "smtp_from_name") or "ORACPC"
	message = f"""
	<p>{_("Hello")},</p>
	<p>{_("Confirm your email to finish creating")} <b>{frappe.utils.escape_html(signup.company_name)}</b>.</p>
	<p>{_("Your site will be")}: <b>{frappe.utils.escape_html(signup.site_name)}</b></p>
	<p><a href="{link}">{_("Confirm email & create account")}</a></p>
	<p>{_("This link expires in {0} hours.").format(TOKEN_HOURS)}</p>
	<p>{from_name}</p>
	"""
	# Prefer dedicated account if present
	kwargs = {
		"recipients": signup.admin_email,
		"subject": subject,
		"message": message,
		"now": True,
	}
	if frappe.db.exists("Email Account", EMAIL_ACCOUNT_NAME):
		kwargs["email_account"] = EMAIL_ACCOUNT_NAME
	frappe.sendmail(**kwargs)


@frappe.whitelist(allow_guest=True)
def suggest_label(company_name: Optional[str] = None):
	return {"site_label": suggest_site_label(company_name or ""), "base_domain": get_base_domain()}


@frappe.whitelist(allow_guest=True)
def get_signup_options():
	return {
		"base_domain": get_base_domain(),
		"email_verification_mode": "Mandatory" if is_email_verification_mandatory() else "Optional",
		"has_server_ip": bool(get_default_server_ip()),
	}


@frappe.whitelist(allow_guest=True)
def register_company(
	company_name: Optional[str] = None,
	site_label: Optional[str] = None,
	admin_email: Optional[str] = None,
	admin_password: Optional[str] = None,
):
	"""Public registration endpoint."""
	company_name = (company_name or "").strip()
	site_label = (site_label or "").strip().lower()
	admin_email = _normalize_email(admin_email or "")
	admin_password = admin_password or ""

	if len(company_name) < 2:
		frappe.throw(_("Company Name is required"))
	if not re.fullmatch(r"[a-z0-9]([a-z0-9-]{1,38}[a-z0-9])?", site_label or ""):
		frappe.throw(
			_("Subdomain must use English letters, numbers, and hyphens only (example: alnoor).")
		)
	if len(admin_password) < 8:
		frappe.throw(_("Password must be at least 8 characters"))
	if not get_default_server_ip():
		frappe.throw(_("Signup is not ready: Default Server IP is missing in Superadmin Settings."))
	if not get_base_domain():
		frappe.throw(_("Signup is not ready: Base Domain is missing in Superadmin Settings."))

	site_name = expand_site_name(site_label)
	_assert_email_available(admin_email)
	_assert_site_available(site_name)

	mandatory = is_email_verification_mandatory()
	token = frappe.generate_hash(length=48) if mandatory else ""
	expires = now_datetime() + timedelta(hours=TOKEN_HOURS) if mandatory else None

	signup = frappe.get_doc(
		{
			"doctype": "Tenant Signup",
			"company_name": company_name,
			"site_label": site_label,
			"site_name": site_name,
			"admin_email": admin_email,
			"admin_password": admin_password,
			"status": "Pending Verification" if mandatory else "Verified",
			"verification_token": token,
			"verification_expires": expires,
			"provision_log": _("Signup received via website."),
		}
	)
	signup.insert(ignore_permissions=True)
	frappe.db.commit()

	if mandatory:
		try:
			_send_verification_email(signup)
			signup.provision_log = _append_log(signup.provision_log, _("Verification email sent."))
			signup.save(ignore_permissions=True)
			frappe.db.commit()
		except Exception:
			signup.provision_log = _append_log(
				signup.provision_log, _("Failed to send email:\n") + frappe.get_traceback()
			)
			signup.save(ignore_permissions=True)
			frappe.db.commit()
			frappe.throw(
				_(
					"Could not send verification email. Check SMTP settings in Superadmin Settings (Mandatory mode)."
				)
			)
		return {
			"ok": True,
			"mode": "Mandatory",
			"message": _("Check your email to confirm and create the account."),
			"signup": signup.name,
			"site_name": site_name,
		}

	# Optional: create immediately
	return _provision_from_signup(signup.name)


def _provision_from_signup(signup_name: str) -> dict:
	signup = frappe.get_doc("Tenant Signup", signup_name)
	tc_name = _create_tenant_company_from_signup(signup)
	signup.tenant_company = tc_name
	signup.status = "Provisioning"
	signup.provision_log = _append_log(signup.provision_log, _("Created Tenant Company {0}").format(tc_name))
	signup.save(ignore_permissions=True)
	frappe.db.commit()

	result = _enqueue_provision(tc_name)
	signup.provision_log = _append_log(signup.provision_log, _("Provision queued: {0}").format(result))
	signup.save(ignore_permissions=True)
	frappe.db.commit()
	return {
		"ok": True,
		"mode": "Optional",
		"message": _("Account creation started. Your site will be ready shortly."),
		"signup": signup.name,
		"tenant_company": tc_name,
		"site_name": signup.site_name,
		"site_url": f"https://{signup.site_name}",
		**result,
	}


@frappe.whitelist(allow_guest=True)
def verify_signup_email(token: Optional[str] = None):
	token = (token or "").strip()
	if not token:
		frappe.throw(_("Missing verification token"))

	name = frappe.db.get_value("Tenant Signup", {"verification_token": token}, "name")
	if not name:
		frappe.throw(_("Invalid or already used verification link"))

	signup = frappe.get_doc("Tenant Signup", name)
	if signup.status not in ("Pending Verification",):
		if signup.status in ("Provisioning", "Active", "Verified"):
			return {
				"ok": True,
				"message": _("Email already confirmed."),
				"site_name": signup.site_name,
				"site_url": f"https://{signup.site_name}",
				"status": signup.status,
			}
		frappe.throw(_("This signup cannot be verified (status: {0}).").format(signup.status))

	if signup.verification_expires and now_datetime() > signup.verification_expires:
		signup.status = "Expired"
		signup.save(ignore_permissions=True)
		frappe.db.commit()
		frappe.throw(_("Verification link has expired. Please sign up again."))

	signup.status = "Verified"
	signup.verification_token = ""
	signup.provision_log = _append_log(signup.provision_log, _("Email verified."))
	signup.save(ignore_permissions=True)
	frappe.db.commit()
	return _provision_from_signup(signup.name)




def _ui_progress_step(percent: float, stage: str, ready: bool, failed: bool) -> str:
	if failed:
		return "provision"
	if ready:
		return "ready"
	stage_text = (stage or "")
	stage_l = stage_text.lower()
	if (
		percent >= 86
		or "ssl" in stage_l
		or "شهادة" in stage_text
		or "تفعيل" in stage_text
	):
		return "ssl"
	if percent >= 15:
		return "provision"
	return "register"


@frappe.whitelist(allow_guest=True)
def get_provision_progress(signup: Optional[str] = None, tenant_company: Optional[str] = None):
	"""Poll provisioning progress for public signup UI."""
	from superadmin.api import is_tenant_ssl_ready

	signup_name = (signup or "").strip()
	tc_name = (tenant_company or "").strip()
	site_name = None
	signup_status = None

	if signup_name:
		if not frappe.db.exists("Tenant Signup", signup_name):
			frappe.throw(_("Signup not found"))
		row = frappe.db.get_value(
			"Tenant Signup",
			signup_name,
			["name", "status", "site_name", "tenant_company", "admin_email"],
			as_dict=True,
		)
		signup_status = row.status
		site_name = row.site_name
		tc_name = tc_name or (row.tenant_company or "")
		admin_email = row.admin_email
	else:
		admin_email = None

	percent = 5
	stage = _("Queued")
	status = signup_status or "Provisioning"
	ready = False
	failed = False
	ssl_ready = False

	if tc_name and frappe.db.exists("Tenant Company", tc_name):
		tc = frappe.db.get_value(
			"Tenant Company",
			tc_name,
			["status", "progress_percent", "progress_stage", "site_name", "company_access", "admin_email"],
			as_dict=True,
		)
		site_name = tc.site_name or site_name
		admin_email = admin_email or tc.admin_email
		percent = float(tc.progress_percent or 0)
		stage = tc.progress_stage or tc.status or stage
		status = tc.status
		ssl_ready = is_tenant_ssl_ready(site_name) if site_name else True
		if tc.status == "Active":
			# Provision job only flips Active after SSL wait completes
			ready = True
			percent = 100
			stage = _("Completed")
			ssl_ready = True
			if signup_name and signup_status != "Active":
				frappe.db.set_value("Tenant Signup", signup_name, "status", "Active")
				frappe.db.commit()
		elif tc.status == "Failed":
			failed = True
		elif not ssl_ready and percent >= 86:
			# Still provisioning / waiting on certificate
			stage = stage or _("Activating SSL")
			percent = max(percent, 88)
	elif signup_status == "Pending Verification":
		percent = 10
		stage = _("Waiting for email confirmation")
	elif signup_status == "Verified":
		percent = 20
		stage = _("Starting provisioning")
	elif signup_status == "Failed":
		failed = True
		percent = percent or 0
		stage = _("Failed")

	step = _ui_progress_step(percent, stage, ready, failed)
	return {
		"ok": True,
		"signup": signup_name,
		"tenant_company": tc_name,
		"site_name": site_name,
		"admin_email": admin_email,
		"percent": percent,
		"stage": stage,
		"status": status,
		"ready": ready,
		"failed": failed,
		"ssl_ready": ssl_ready,
		"step": step,
		"site_url": f"https://{site_name}" if site_name else None,
		"login_url": f"/portal-login?email={admin_email}" if admin_email else "/portal-login",
	}

@frappe.whitelist(allow_guest=True)
def resolve_login_portal(admin_email: Optional[str] = None):
	"""Find tenant site for an administrator email and return redirect URL."""
	email = _normalize_email(admin_email or "")
	# Prefer active Tenant Company
	row = frappe.db.get_value(
		"Tenant Company",
		{"admin_email": email, "status": "Active"},
		["name", "site_name", "company_access"],
		as_dict=True,
	)
	if not row:
		# fallback any Tenant Company with this email
		row = frappe.db.get_value(
			"Tenant Company",
			{"admin_email": email},
			["name", "site_name", "status", "company_access"],
			as_dict=True,
		)
	if not row:
		frappe.throw(_("No company account found for this email."))

	site = row.site_name
	if row.get("company_access") == "Suspended":
		frappe.throw(_("This company is suspended. Contact support."))
	if row.get("status") and row.status != "Active":
		frappe.throw(_("Company site is not ready yet (status: {0}).").format(row.status))

	return {
		"ok": True,
		"site_name": site,
		"redirect_to": f"https://{site}/login",
	}
