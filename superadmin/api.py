import json
import os
import re
import shutil
import subprocess

import frappe
from frappe import _
from frappe.utils import get_bench_path

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


def _read_mariadb_root_from_config_files() -> str | None:
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
	# site-specific override
	site = getattr(frappe.local, "site", None) if frappe.local else None
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
	env = os.environ.get("SUPERADMIN_MARIADB_ROOT_PASSWORD")
	if env:
		return env.strip(), "env:SUPERADMIN_MARIADB_ROOT_PASSWORD"
	file_pw = _read_mariadb_root_from_config_files()
	if file_pw:
		return file_pw, "sites/common_site_config.json or sites/<site>/site_config.json (direct read)"
	frappe.throw(
		_(
			"Set `{0}` in sites/common_site_config.json or sites/<site>/site_config.json, "
			"or environment variable SUPERADMIN_MARIADB_ROOT_PASSWORD."
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


def _append_log(existing: str | None, text: str) -> str:
	return ((existing or "").rstrip() + "\n\n" + text.strip()).strip()[-65000:]


def _set_progress(
	doc,
	percent: int,
	stage: str,
	status: str | None = None,
	log_text: str | None = None,
	append_log: bool = True,
):
	doc.reload()
	if status:
		doc.status = status
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


def _configure_tenant_admin(site_name: str, admin_email: str, admin_pw: str, company_name: str):
	management_site = frappe.local.site
	frappe.destroy()
	try:
		frappe.init(site=site_name)
		frappe.connect()
		frappe.set_user("Administrator")

		if frappe.db.exists("User", admin_email):
			user = frappe.get_doc("User", admin_email)
			user.enabled = 1
			user.first_name = user.first_name or company_name or admin_email
		else:
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": admin_email,
					"first_name": company_name or admin_email,
					"enabled": 1,
					"send_welcome_email": 0,
					"roles": [{"role": "System Manager"}],
				}
			)
			user.insert(ignore_permissions=True)

		existing_roles = {role.role for role in user.get("roles")}
		if "System Manager" not in existing_roles:
			user.append("roles", {"role": "System Manager"})
		user.save(ignore_permissions=True)

		from frappe.utils.password import update_password

		update_password(admin_email, admin_pw)
		frappe.db.commit()
	finally:
		frappe.destroy()
		frappe.init(site=management_site)
		frappe.connect()


def _bench_executable() -> str:
	path = shutil.which("bench")
	if path:
		return path
	candidate = os.path.join(get_bench_path(), "env", "bin", "bench")
	if os.path.isfile(candidate):
		return candidate
	frappe.throw(_("Could not find `bench` on PATH or in bench/env/bin."))


def _site_path(site_name: str) -> str:
	return os.path.join(get_bench_path(), "sites", site_name)


def _site_exists(site_name: str) -> bool:
	return os.path.isdir(_site_path(site_name))


def _site_has_app(site_name: str, app_name: str) -> bool:
	apps_txt = os.path.join(_site_path(site_name), "apps.txt")
	if not os.path.isfile(apps_txt):
		return False
	with open(apps_txt, encoding="utf-8") as f:
		return app_name in {line.strip() for line in f if line.strip()}


@frappe.whitelist()
def create_tenant_site(docname: str):
	frappe.only_for("System Manager")

	doc = frappe.get_doc("Tenant Company", docname)
	if doc.status == "Active":
		frappe.throw(_("Site is already active."))
	if doc.status in ("Queued", "Provisioning"):
		frappe.throw(_("Provisioning is already in progress."))

	_validate_site_name(doc.site_name)
	admin_pw = doc.get_password("admin_password")
	if not admin_pw:
		frappe.throw(_("Set Administrator Password before creating the site."))

	doc.status = "Queued"
	doc.progress_percent = 5
	doc.progress_stage = _("Queued")
	doc.provision_log = _("Queued provisioning job.")
	doc.save(ignore_permissions=True)
	frappe.db.commit()

	job = frappe.enqueue(
		"superadmin.api._provision_job",
		queue="long",
		timeout=7200,
		job_id=f"superadmin-provision-{docname}-{frappe.generate_hash(length=8)}",
		job_name=f"superadmin-provision-{docname}",
		docname=docname,
	)
	doc.reload()
	doc.provision_log = _append_log(doc.provision_log, _("RQ job queued: {0}").format(job.id))
	doc.save(ignore_permissions=True)
	frappe.db.commit()

	return {"status": "queued", "job_id": job.id}


def _provision_job(docname: str):
	"""Background worker: site context is already the management site (e.g. site1.local)."""
	doc = frappe.get_doc("Tenant Company", docname)
	_set_progress(doc, 10, _("Preparing"), status="Provisioning", log_text=_("Starting tenant provisioning."))

	site_name = doc.site_name.strip()
	root_pw, root_pw_source = _resolve_mariadb_root_password()
	admin_pw = doc.get_password("admin_password")
	admin_email = (doc.admin_email or "").strip()
	company_name = (doc.company_name or "").strip()

	bench = _bench_executable()
	cwd = get_bench_path()

	new_site_cmd = [
		bench,
		"new-site",
		site_name,
		"--mariadb-root-password",
		root_pw,
		"--admin-password",
		admin_pw,
		"--verbose",
	]
	install_erpnext_cmd = [bench, "--site", site_name, "install-app", "erpnext"]

	preview = (
		_("MariaDB root password resolved from: {0}\n").format(root_pw_source)
		+ _("Step 1: {0}\n").format(_mask_cmd(new_site_cmd))
		+ _("Step 2: {0}\n").format(_mask_cmd(install_erpnext_cmd))
		+ _("CWD: {0}\nBench binary: {1}\n").format(cwd, bench)
	)

	try:
		if _site_exists(site_name):
			_set_progress(
				doc,
				50,
				_("Installing ERPNext"),
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
			_set_progress(doc, 50, _("Installing ERPNext"), log_text="--- new-site output ---\n" + new_site_log)

		if _site_has_app(site_name, "erpnext"):
			_set_progress(
				doc,
				80,
				_("Creating administrator account"),
				log_text=_("ERPNext is already installed on {0}. Skipping install-app.").format(site_name),
			)
		else:
			erpnext_log = _run_bench_command(install_erpnext_cmd, cwd)
			_set_progress(
				doc,
				80,
				_("Creating administrator account"),
				log_text="--- install-app erpnext output ---\n" + erpnext_log,
			)

		_configure_tenant_admin(site_name, admin_email, admin_pw, company_name)
		doc = frappe.get_doc("Tenant Company", docname)
		_set_progress(
			doc,
			100,
			_("Completed"),
			status="Active",
			log_text=_("Created administrator user {0} on {1}.").format(admin_email, site_name),
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
