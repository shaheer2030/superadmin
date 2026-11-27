from __future__ import annotations

import json
import os
import re
import socket
import ssl
import subprocess
import time
from typing import List, Optional

import frappe
from frappe import _
from frappe.utils import get_bench_path

from superadmin.compat import (
	app_on_bench,
	default_tenant_apps,
	filter_supported_bench_args,
	find_bench_executable,
	new_site_extra_args,
	with_site,
)

SITE_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9\-\.]*[a-z0-9]$", re.IGNORECASE)
KEY = "superadmin_mariadb_root_password"


def _validate_site_name(site_name: str) -> None:
	site_name = site_name.strip()
	if len(site_name) < 3:
		frappe.throw(_("Site Name is too short"))
	if not SITE_NAME_PATTERN.match(site_name):
		frappe.throw(
			_("Site Name must look like a hostname (letters, digits, dots, hyphens), e.g. company1.local")
		)


def _read_mariadb_root_from_config_files() -> Optional[str]:
	"""Worker-safe: read key directly from JSON in case conf merge/cache differs from web request."""
	bench_path = get_bench_path()
	sites = os.path.join(bench_path, "sites")
	for name in ("common_site_config.json",):
		full = os.path.join(sites, name)
		if not os.path.isfile(full):
			continue
		try:
			with open(full, encoding="utf-8") as f:
				data = json.load(f)
			pw = data.get(KEY)
			if pw:
				return str(pw).strip() or None
		except (OSError, json.JSONDecodeError, TypeError):
			continue
	site = getattr(frappe.local, "site", None) if getattr(frappe, "local", None) else None
	if site:
		sp = os.path.join(sites, site, "site_config.json")
		if os.path.isfile(sp):
			try:
				with open(sp, encoding="utf-8") as f:
					data = json.load(f)
				pw = data.get(KEY)
				if pw:
					return str(pw).strip() or None
			except (OSError, json.JSONDecodeError, TypeError):
				pass
	return None


def _resolve_mariadb_root_password():
	"""Returns (password, human-readable source) for logging; prefers conf, then env, then JSON files."""
	conf_pw = frappe.conf.get(KEY)
	if conf_pw:
		return str(conf_pw).strip(), "frappe.conf"
	# Common docker / compose env aliases (never log values).
	for env_key in (
		"SUPERADMIN_MARIADB_ROOT_PASSWORD",
		"DB_PASSWORD",
		"MYSQL_ROOT_PASSWORD",
		"MARIADB_ROOT_PASSWORD",
	):
		env = os.environ.get(env_key)
		if env:
			return env.strip(), f"env:{env_key}"
	file_pw = _read_mariadb_root_from_config_files()
	if file_pw:
		return file_pw, "sites/common_site_config.json or sites/<site>/site_config.json (direct read)"
	frappe.throw(
		_(
			"Set `{0}` in sites/common_site_config.json or sites/<site>/site_config.json, "
			"or environment variable SUPERADMIN_MARIADB_ROOT_PASSWORD / DB_PASSWORD."
		).format(KEY)
	)


def _mask_cmd(cmd: list) -> str:
	out = []
	for i, arg in enumerate(cmd):
		if i > 0 and cmd[i - 1] in ("--mariadb-root-password", "--admin-password"):
			out.append("***")
		else:
			out.append(arg)
	return " ".join(out)


def _append_log(existing: Optional[str], text: str) -> str:
	return ((existing or "").rstrip() + "\n\n" + text.strip()).strip()[-65000:]


def _set_progress(
	doc,
	percent: int,
	stage: str,
	status: Optional[str] = None,
	log_text: Optional[str] = None,
	append_log: bool = True,
	company_access: Optional[str] = None,
):
	doc.reload()
	if status:
		doc.status = status
	if company_access is not None:
		doc.company_access = company_access
	doc.progress_percent = percent
	doc.progress_stage = stage
	if log_text is not None:
		doc.provision_log = _append_log(doc.provision_log, log_text) if append_log else log_text[-65000:]
	doc.save(ignore_permissions=True)
	frappe.db.commit()


def _run_bench_command(cmd: list, cwd: str, timeout: int = 3600) -> str:
	completed = subprocess.run(
		cmd,
		cwd=cwd,
		text=True,
		capture_output=True,
		timeout=timeout,
		check=False,
		env=os.environ.copy(),
	)
	log = (completed.stdout or "") + "\n" + (completed.stderr or "")
	if completed.returncode != 0:
		raise RuntimeError(log.strip() or f"Command failed with return code {completed.returncode}")
	return log


# Full company-owner role set. System Manager alone does NOT grant ERPNext
# module DocTypes (Sales Order, Bin, reports, …) — those need domain roles.
TENANT_ADMIN_ROLES = (
	"System Manager",
	"Accounts Manager",
	"Accounts User",
	"Sales Manager",
	"Sales User",
	"Sales Master Manager",
	"Purchase Manager",
	"Purchase User",
	"Purchase Master Manager",
	"Stock Manager",
	"Stock User",
	"Item Manager",
	"Manufacturing Manager",
	"Manufacturing User",
	"Projects Manager",
	"Projects User",
	"HR Manager",
	"HR User",
	"Quality Manager",
	"Maintenance Manager",
	"Maintenance User",
	"Delivery Manager",
	"Delivery User",
	"Fleet Manager",
	"Report Manager",
	"Workspace Manager",
	"Analytics",
	"Auditor",
)


def _tenant_admin_roles() -> list:
	"""Return roles that exist on the current site (skip missing custom roles)."""
	available = set(frappe.get_all("Role", pluck="name", filters={"disabled": 0}))
	return [role for role in TENANT_ADMIN_ROLES if role in available]


def _ensure_tenant_admin_roles(user) -> None:
	wanted = _tenant_admin_roles()
	existing = {row.role for row in (user.get("roles") or [])}
	added = False
	for role in wanted:
		if role not in existing:
			user.append("roles", {"role": role})
			added = True
	if added or not existing:
		user.save(ignore_permissions=True)


def _configure_tenant_admin(site_name: str, admin_email: str, admin_pw: str, company_name: str):
	def _inner():
		frappe.set_user("Administrator")

		if frappe.db.exists("User", admin_email):
			user = frappe.get_doc("User", admin_email)
			user.enabled = 1
			user.first_name = user.first_name or company_name or admin_email
			if getattr(user, "user_type", None) != "System User":
				user.user_type = "System User"
			user.save(ignore_permissions=True)
		else:
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": admin_email,
					"first_name": company_name or admin_email,
					"enabled": 1,
					"send_welcome_email": 0,
					"user_type": "System User",
					"roles": [{"role": "System Manager"}],
				}
			)
			user.insert(ignore_permissions=True)

		_ensure_tenant_admin_roles(user)

		from frappe.utils.password import update_password

		update_password(admin_email, admin_pw)
		frappe.db.commit()

	with_site(site_name, _inner)


def _site_path(site_name: str) -> str:
	return os.path.join(get_bench_path(), "sites", site_name)


def _site_exists(site_name: str) -> bool:
	return os.path.isdir(_site_path(site_name))


def _site_has_app(site_name: str, app_name: str) -> bool:
	apps_txt = os.path.join(_site_path(site_name), "apps.txt")
	if not os.path.isfile(apps_txt):
		# Fallback used by newer Frappe layouts.
		alt = os.path.join(_site_path(site_name), "site_config.json")
		if os.path.isfile(alt):
			try:
				with open(alt, encoding="utf-8") as f:
					data = json.load(f)
				installed = data.get("installed_apps") or []
				return app_name in installed
			except (OSError, json.JSONDecodeError, TypeError):
				return False
		return False
	with open(apps_txt, encoding="utf-8") as f:
		return app_name in {line.strip() for line in f if line.strip()}


def _hook_default_install_apps() -> list:
	"""Resolve `superadmin_default_install_apps` from hooks (all installed apps merged)."""
	h = frappe.get_hooks("superadmin_default_install_apps") or []
	out = []
	for item in h:
		if isinstance(item, (list, tuple)):
			out.extend(str(x).strip() for x in item if str(x).strip())
		else:
			s = str(item).strip()
			if s:
				out.append(s)
	return out or default_tenant_apps()


def _apps_to_install(doc) -> list:
	"""Per-tenant → common_site_config → hooks/default detection."""
	raw = (getattr(doc, "install_apps", None) or "").strip()
	if raw:
		return [p.strip() for p in re.split(r"[\n,]+", raw) if p.strip()]
	conf = frappe.conf.get("superadmin_tenant_install_apps")
	if isinstance(conf, (list, tuple)) and len(conf) > 0:
		return [str(x).strip() for x in conf if str(x).strip()]
	if isinstance(conf, str) and conf.strip():
		return [p.strip() for p in re.split(r"[\n,]+", conf) if p.strip()]
	return _hook_default_install_apps()


def _validate_apps_on_bench(app_names: list) -> None:
	missing = [a for a in app_names if not app_on_bench(a)]
	if missing:
		frappe.throw(
			_("These apps are missing under bench/apps — clone or get-app them first: {0}").format(
				", ".join(missing)
			)
		)


def _build_new_site_command(bench: str, site_name: str, root_pw: str, admin_pw: str) -> List[str]:
	cmd = [
		bench,
		"new-site",
		site_name,
		"--mariadb-root-password",
		root_pw,
		"--admin-password",
		admin_pw,
	]
	cmd.extend(new_site_extra_args())
	return filter_supported_bench_args(cmd)



def _ssl_queue_dir() -> str:
	return os.path.join(get_bench_path(), "apps", "superadmin", "ssl-queue")


def _ssl_req_basename(site_name: str) -> str:
	return f"{(site_name or '').strip().lower()}.req"


def _ssl_is_applicable(site_name: str) -> bool:
	site_name = (site_name or "").strip().lower()
	if not site_name.endswith(".oracpc.tech") or site_name.count(".") < 2:
		return False
	if site_name == "oracpc.tech" or site_name.startswith("www."):
		return False
	return True


def _ssl_status(site_name: str) -> str:
	"""Return skipped | pending | done | failed | unknown for a tenant hostname."""
	site_name = (site_name or "").strip().lower()
	if not _ssl_is_applicable(site_name):
		return "skipped"
	queue_dir = _ssl_queue_dir()
	name = _ssl_req_basename(site_name)
	active = os.path.join(queue_dir, "active", f"{site_name}.ok")
	if os.path.exists(active) or os.path.exists(os.path.join(queue_dir, "done", name)):
		return "done"
	if os.path.exists(os.path.join(queue_dir, "failed", name)):
		return "failed"
	if os.path.exists(os.path.join(queue_dir, name)):
		return "pending"
	return "unknown"


def _mark_ssl_active(site_name: str) -> None:
	"""Durable marker kept until tenant host cleanup runs."""
	site_name = (site_name or "").strip().lower()
	if not _ssl_is_applicable(site_name):
		return
	queue_dir = _ssl_queue_dir()
	active_dir = os.path.join(queue_dir, "active")
	try:
		os.makedirs(active_dir, exist_ok=True)
		with open(os.path.join(active_dir, f"{site_name}.ok"), "w", encoding="utf-8") as f:
			f.write(site_name + "\n")
	except OSError:
		pass


def _https_certificate_ok(site_name: str, timeout: float = 6.0) -> bool:
	"""True when public HTTPS presents a valid cert for the tenant hostname."""
	site_name = (site_name or "").strip().lower()
	if not site_name:
		return False
	try:
		ctx = ssl.create_default_context()
		with socket.create_connection((site_name, 443), timeout=timeout) as sock:
			with ctx.wrap_socket(sock, server_hostname=site_name) as ssock:
				return bool(ssock.getpeercert())
	except Exception:
		return False


def is_tenant_ssl_ready(site_name: str) -> bool:
	"""Public helper: SSL not required, already issued, or HTTPS handshake succeeds."""
	status = _ssl_status(site_name)
	if status in ("skipped", "done"):
		return True
	if status == "failed":
		return False
	return _https_certificate_ok(site_name)


def _queue_tenant_ssl(site_name: str) -> str:
	"""Ask the host SSL worker to issue a Let's Encrypt cert for *.oracpc.tech tenants.

	The provision job runs inside Docker and cannot reload host nginx, so it drops a
	request file that `/home/ubuntu/gitops/scripts/process-ssl-queue.sh` picks up.
	"""
	site_name = (site_name or "").strip().lower()
	if not _ssl_is_applicable(site_name):
		if site_name == "oracpc.tech" or site_name.startswith("www."):
			return _("SSL skipped: management hostname.")
		return _("SSL skipped: Site Name is not a subdomain of oracpc.tech.")
	queue_dir = _ssl_queue_dir()
	try:
		os.makedirs(queue_dir, exist_ok=True)
		os.makedirs(os.path.join(queue_dir, "done"), exist_ok=True)
		os.makedirs(os.path.join(queue_dir, "failed"), exist_ok=True)
		os.makedirs(os.path.join(queue_dir, "active"), exist_ok=True)
		failed = os.path.join(queue_dir, "failed", _ssl_req_basename(site_name))
		if os.path.exists(failed):
			try:
				os.remove(failed)
			except OSError:
				pass
		if _ssl_status(site_name) == "done":
			return _("SSL certificate already issued for {0}.").format(site_name)
		req = os.path.join(queue_dir, _ssl_req_basename(site_name))
		with open(req, "w", encoding="utf-8") as f:
			f.write(site_name + "\n")
		return _("Queued SSL certificate request for {0} (host worker issues it within ~1 minute).").format(
			site_name
		)
	except OSError as e:
		return _("Could not queue SSL request: {0}").format(str(e))


def _wait_for_tenant_ssl(doc, site_name: str, timeout: int = 600, poll_seconds: int = 5) -> str:
	"""Block provision until host SSL worker finishes (or skip when not applicable)."""
	site_name = (site_name or "").strip().lower()
	queue_note = _queue_tenant_ssl(site_name)
	status = _ssl_status(site_name)

	if status == "skipped":
		return queue_note
	if status == "done":
		_mark_ssl_active(site_name)
		if _https_certificate_ok(site_name):
			return queue_note + "\n" + _("SSL already active for {0}.").format(site_name)
		time.sleep(2)
		return queue_note + "\n" + _("SSL marker ready for {0}.").format(site_name)

	_set_progress(
		doc,
		88,
		_("Activating SSL"),
		log_text=queue_note + "\n" + _("Waiting for Let's Encrypt certificate..."),
	)

	started = time.time()
	last_log_at = 0.0
	while time.time() - started < timeout:
		elapsed = int(time.time() - started)
		percent = min(96, 88 + int((elapsed / max(timeout, 1)) * 8))
		status = _ssl_status(site_name)

		log_text = None
		if elapsed - last_log_at >= 30:
			log_text = _("Still waiting for SSL ({0}s, status={1})...").format(elapsed, status)
			last_log_at = float(elapsed)

		_set_progress(doc, percent, _("Activating SSL"), log_text=log_text)

		if status == "failed":
			raise RuntimeError(
				_("SSL issuance failed for {0}. Check /opt/erpnext-apps/superadmin/ssl-queue/processor.log").format(
					site_name
				)
			)

		if status == "done":
			_mark_ssl_active(site_name)
			for _attempt in range(6):
				if _https_certificate_ok(site_name):
					return _("SSL certificate active for {0}.").format(site_name)
				time.sleep(2)
			return _("SSL certificate issued for {0}.").format(site_name)

		if _https_certificate_ok(site_name):
			_mark_ssl_active(site_name)
			return _("HTTPS already serving a valid certificate for {0}.").format(site_name)

		time.sleep(poll_seconds)

	raise RuntimeError(_("Timed out waiting for SSL certificate for {0}.").format(site_name))


@frappe.whitelist()
def create_tenant_site(docname: str):
	frappe.only_for("System Manager")

	doc = frappe.get_doc("Tenant Company", docname)
	if doc.status == "Active":
		frappe.throw(_("Site is already active."))
	if doc.status in ("Queued", "Provisioning"):
		frappe.throw(_("Provisioning is already in progress."))

	from superadmin.superadmin.doctype.superadmin_settings.superadmin_settings import expand_site_name

	expanded = expand_site_name(doc.site_name)
	if expanded != (doc.site_name or "").strip().lower().rstrip("."):
		doc.site_name = expanded
		doc.save(ignore_permissions=True)
		frappe.db.commit()
	_validate_site_name(doc.site_name)
	admin_pw = doc.get_password("admin_password")
	if not admin_pw:
		frappe.throw(_("Set Administrator Password before creating the site."))

	apps_to_install = _apps_to_install(doc)
	# Allow empty list only when user explicitly cleared install_apps and wants frappe-only site.
	explicit_empty = (getattr(doc, "install_apps", None) or "").strip() == "" and frappe.conf.get(
		"superadmin_tenant_install_apps"
	) in (None, "", [], ())
	if not apps_to_install and not explicit_empty:
		# Still OK: frappe-only tenant.
		apps_to_install = []
	_validate_apps_on_bench(apps_to_install)

	doc.status = "Queued"
	doc.progress_percent = 5
	doc.progress_stage = _("Queued")
	doc.provision_log = _("Queued provisioning job.")
	doc.save(ignore_permissions=True)
	frappe.db.commit()

	enqueue_kwargs = {
		"queue": "long",
		"timeout": 7200,
		"job_name": f"superadmin-provision-{docname}",
		"docname": docname,
	}
	# job_id exists on modern Frappe; older versions ignore unknown kwargs poorly — use try/except.
	try:
		job = frappe.enqueue(
			"superadmin.api._provision_job",
			job_id=f"superadmin-provision-{docname}-{frappe.generate_hash(length=8)}",
			**enqueue_kwargs,
		)
	except TypeError:
		job = frappe.enqueue("superadmin.api._provision_job", **enqueue_kwargs)

	doc.reload()
	job_id = getattr(job, "id", None) or getattr(job, "id", "") or str(job)
	doc.provision_log = _append_log(doc.provision_log, _("RQ job queued: {0}").format(job_id))
	doc.save(ignore_permissions=True)
	frappe.db.commit()

	return {"status": "queued", "job_id": job_id}


def _provision_job(docname: str):
	"""Background worker: site context is already the management site."""
	doc = frappe.get_doc("Tenant Company", docname)
	_set_progress(doc, 10, _("Preparing"), status="Provisioning", log_text=_("Starting tenant provisioning."))

	site_name = doc.site_name.strip()
	root_pw, root_pw_source = _resolve_mariadb_root_password()
	admin_pw = doc.get_password("admin_password")
	admin_email = (doc.admin_email or "").strip()
	company_name = (doc.company_name or "").strip()
	apps_to_install = _apps_to_install(doc)
	_validate_apps_on_bench(apps_to_install)

	bench = find_bench_executable()
	cwd = get_bench_path()
	new_site_cmd = _build_new_site_command(bench, site_name, root_pw, admin_pw)

	preview = (
		_("MariaDB root password resolved from: {0}\n").format(root_pw_source)
		+ _("Step 1: {0}\n").format(_mask_cmd(new_site_cmd))
		+ _("Apps to install: {0}\n").format(", ".join(apps_to_install) or _("(frappe only)"))
	)
	for app_name in apps_to_install:
		preview += _("Then: {0}\n").format(
			_mask_cmd([bench, "--site", site_name, "install-app", app_name])
		)
	preview += _("CWD: {0}\nBench binary: {1}\n").format(cwd, bench)

	try:
		if _site_exists(site_name):
			_set_progress(
				doc,
				50,
				_("Installing applications"),
				log_text=preview
				+ "\n"
				+ _("Site {0} already exists. Skipping new-site and continuing retry.").format(site_name),
				append_log=False,
			)
		else:
			_set_progress(
				doc,
				20,
				_("Creating site"),
				log_text=preview + "\n" + _("Creating new Frappe site..."),
				append_log=False,
			)
			new_site_log = _run_bench_command(new_site_cmd, cwd)
			_set_progress(doc, 50, _("Installing applications"), log_text="--- new-site output ---\n" + new_site_log)

		n_apps = max(len(apps_to_install), 1)
		for idx, app_name in enumerate(apps_to_install):
			pct = 50 + int(35 * (idx + 1) / n_apps)
			pct = min(pct, 85)
			if _site_has_app(site_name, app_name):
				_set_progress(
					doc,
					pct,
					_("Checking {0}").format(app_name),
					log_text=_("{0} is already on site {1}. Skipping install-app.").format(app_name, site_name),
				)
			else:
				install_cmd = [bench, "--site", site_name, "install-app", app_name]
				app_log = _run_bench_command(install_cmd, cwd)
				_set_progress(
					doc,
					pct,
					_("Installing {0}").format(app_name),
					log_text="--- install-app {0} ---\n{1}".format(app_name, app_log),
				)

		_configure_tenant_admin(site_name, admin_email, admin_pw, company_name)
		doc = frappe.get_doc("Tenant Company", docname)
		_set_progress(
			doc,
			86,
			_("Preparing SSL"),
			log_text=_("Created administrator user {0} on {1}.").format(admin_email, site_name),
		)
		ssl_note = _wait_for_tenant_ssl(doc, site_name)
		doc = frappe.get_doc("Tenant Company", docname)
		_set_progress(
			doc,
			100,
			_("Completed"),
			status="Active",
			log_text=ssl_note,
			company_access="Active",
		)
	except Exception:
		doc.reload()
		_set_progress(
			doc,
			doc.progress_percent or 0,
			_("Failed"),
			status="Failed",
			log_text="--- exception ---\n" + frappe.get_traceback(),
		)
		raise


PROTECTED_SITES = frozenset({"oracpc.tech", "www.oracpc.tech"})


def _assert_deletable_site_name(site_name: str) -> str:
	site_name = (site_name or "").strip().lower()
	if not site_name:
		frappe.throw(_("Site Name is required for deletion."))
	if site_name in PROTECTED_SITES:
		frappe.throw(_("Refusing to delete protected management site: {0}").format(site_name))
	management = (getattr(getattr(frappe, "local", None), "site", None) or "").strip().lower()
	if management and site_name == management:
		frappe.throw(_("Refusing to delete the current management site: {0}").format(site_name))
	_validate_site_name(site_name)
	return site_name


def _queue_tenant_host_cleanup(site_name: str) -> str:
	"""Ask host cron to remove nginx vhost + Let's Encrypt cert for this tenant."""
	site_name = (site_name or "").strip().lower()
	queue_dir = os.path.join(get_bench_path(), "apps", "superadmin", "ssl-queue", "cleanup")
	try:
		os.makedirs(queue_dir, exist_ok=True)
		req = os.path.join(queue_dir, f"{site_name}.del")
		with open(req, "w", encoding="utf-8") as f:
			f.write(site_name + "\n")
		return _("Queued host cleanup (nginx/SSL) for {0}.").format(site_name)
	except OSError as e:
		return _("Could not queue host cleanup: {0}").format(str(e))


def _build_drop_site_command(bench: str, site_name: str, root_pw: str) -> List[str]:
	return [
		bench,
		"drop-site",
		site_name,
		"--db-root-password",
		root_pw,
		"--force",
		"--no-backup",
	]


@frappe.whitelist()
def delete_tenant_company(docname: str, confirm_site_name: Optional[str] = None):
	"""Permanently destroy tenant site + DB + queue host cleanup, then delete the DocType row."""
	frappe.only_for("System Manager")

	doc = frappe.get_doc("Tenant Company", docname)
	if doc.status in ("Queued", "Provisioning", "Deleting"):
		frappe.throw(_("Cannot delete while status is {0}.").format(doc.status))

	site_name = _assert_deletable_site_name(doc.site_name)
	confirm = (confirm_site_name or "").strip().lower()
	if confirm != site_name:
		frappe.throw(
			_("Type the Site Name exactly to confirm permanent delete: {0}").format(site_name)
		)

	doc.status = "Deleting"
	doc.progress_percent = 5
	doc.progress_stage = _("Queued for deletion")
	doc.provision_log = _append_log(
		doc.provision_log,
		_("Queued permanent delete for {0}.").format(site_name),
	)
	doc.save(ignore_permissions=True)
	frappe.db.commit()

	enqueue_kwargs = {
		"queue": "long",
		"timeout": 7200,
		"job_name": f"superadmin-delete-{docname}",
		"docname": docname,
	}
	try:
		job = frappe.enqueue(
			"superadmin.api._delete_job",
			job_id=f"superadmin-delete-{docname}-{frappe.generate_hash(length=8)}",
			**enqueue_kwargs,
		)
	except TypeError:
		job = frappe.enqueue("superadmin.api._delete_job", **enqueue_kwargs)

	doc.reload()
	job_id = getattr(job, "id", None) or str(job)
	doc.provision_log = _append_log(doc.provision_log, _("RQ delete job queued: {0}").format(job_id))
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"status": "queued", "job_id": job_id, "site_name": site_name}


def _delete_job(docname: str):
	"""Background: drop-site (DB+files), queue nginx/SSL cleanup, delete Tenant Company row."""
	doc = frappe.get_doc("Tenant Company", docname)
	site_name = _assert_deletable_site_name(doc.site_name)
	_set_progress(
		doc,
		10,
		_("Preparing deletion"),
		status="Deleting",
		log_text=_("Starting permanent delete for {0}.").format(site_name),
	)

	bench = find_bench_executable()
	cwd = get_bench_path()

	try:
		# Block visitors immediately while we tear down
		try:
			from superadmin.tenant_access import _set_company_suspended_marker

			_set_company_suspended_marker(site_name, True)
		except Exception:
			pass

		if _site_exists(site_name):
			root_pw, root_pw_source = _resolve_mariadb_root_password()
			drop_cmd = _build_drop_site_command(bench, site_name, root_pw)
			_set_progress(
				doc,
				30,
				_("Dropping site"),
				log_text=_("MariaDB root from: {0}\nRunning: {1}").format(
					root_pw_source, _mask_cmd(drop_cmd)
				),
			)
			drop_log = _run_bench_command(drop_cmd, cwd, timeout=7200)
			_set_progress(doc, 70, _("Site dropped"), log_text="--- drop-site ---\n" + drop_log)
		else:
			_set_progress(
				doc,
				70,
				_("No site folder"),
				log_text=_("Site folder {0} not found — skipping drop-site.").format(site_name),
			)

		# Remove leftover site dir if drop-site left anything
		site_path = _site_path(site_name)
		if os.path.isdir(site_path):
			import shutil

			shutil.rmtree(site_path, ignore_errors=True)
			_set_progress(
				doc,
				80,
				_("Removed leftovers"),
				log_text=_("Removed leftover directory {0}.").format(site_path),
			)

		cleanup_note = _queue_tenant_host_cleanup(site_name)
		_set_progress(doc, 90, _("Host cleanup queued"), log_text=cleanup_note)

		# Delete DocType row (bypass on_trash guard)
		frappe.local.superadmin_allow_tenant_delete = True
		frappe.delete_doc("Tenant Company", docname, ignore_permissions=True, force=True)
		frappe.db.commit()
	except Exception:
		# If doc still exists, mark Failed
		if frappe.db.exists("Tenant Company", docname):
			doc = frappe.get_doc("Tenant Company", docname)
			_set_progress(
				doc,
				doc.progress_percent or 0,
				_("Delete failed"),
				status="Failed",
				log_text="--- delete exception ---\n" + frappe.get_traceback(),
			)
		raise
