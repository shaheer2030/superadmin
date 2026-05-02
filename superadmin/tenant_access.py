"""Tenant suspend/activate (maintenance mode). Kept in a separate module so workers
load fresh code when the app is updated; avoid relying on a stale `superadmin.api` in sys.modules.
"""

import os
import shutil
import subprocess

import frappe
from frappe import _
from frappe.utils import get_bench_path


def _append_log(existing: str | None, text: str) -> str:
	return ((existing or "").rstrip() + "\n\n" + text.strip()).strip()[-65000:]


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


def _run_set_maintenance_mode(site_name: str, turn_on: bool) -> str:
	bench = _bench_executable()
	cwd = get_bench_path()
	state = "on" if turn_on else "off"
	cmd = [bench, "--site", site_name, "set-maintenance-mode", state]
	return _run_bench_command(cmd, cwd, timeout=300)


@frappe.whitelist()
def suspend_tenant_company(docname: str):
	"""Put tenant site in maintenance mode (company suspended)."""
	frappe.only_for("System Manager")
	doc = frappe.get_doc("Tenant Company", docname)
	if doc.status != "Active":
		frappe.throw(_("Suspend is only available when Status is Active."))
	site_name = (doc.site_name or "").strip()
	if not site_name:
		frappe.throw(_("Set Site Name first."))
	if not _site_exists(site_name):
		frappe.throw(_("Site folder not found: {0}").format(site_name))
	if (doc.company_access or "Active") == "Suspended":
		frappe.msgprint(_("Company is already suspended."))
		return {"ok": True, "company_access": "Suspended"}
	try:
		log = _run_set_maintenance_mode(site_name, turn_on=True)
	except Exception as e:
		frappe.throw(_("Could not suspend site: {0}").format(str(e)))
	doc.reload()
	doc.company_access = "Suspended"
	doc.provision_log = _append_log(
		doc.provision_log, _("--- suspend ---\n{0}").format(log[-8000:])
	)
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"ok": True, "company_access": "Suspended"}


@frappe.whitelist()
def activate_tenant_company(docname: str):
	"""Clear maintenance mode for tenant site (company active)."""
	frappe.only_for("System Manager")
	doc = frappe.get_doc("Tenant Company", docname)
	if doc.status != "Active":
		frappe.throw(_("Activate is only available when Status is Active."))
	site_name = (doc.site_name or "").strip()
	if not site_name:
		frappe.throw(_("Set Site Name first."))
	if not _site_exists(site_name):
		frappe.throw(_("Site folder not found: {0}").format(site_name))
	if (doc.company_access or "Active") == "Active":
		frappe.msgprint(_("Company is already active."))
		return {"ok": True, "company_access": "Active"}
	try:
		log = _run_set_maintenance_mode(site_name, turn_on=False)
	except Exception as e:
		frappe.throw(_("Could not activate site: {0}").format(str(e)))
	doc.reload()
	doc.company_access = "Active"
	doc.provision_log = _append_log(
		doc.provision_log, _("--- activate ---\n{0}").format(log[-8000:])
	)
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"ok": True, "company_access": "Active"}
