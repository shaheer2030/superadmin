"""Tenant site backups via bench CLI."""

from __future__ import annotations

import glob
import os
import time
from typing import Optional

import frappe
from frappe import _
from frappe.utils import get_bench_path, now_datetime

from superadmin import audit
from superadmin.compat import find_bench_executable
from superadmin.tenant_access import _run_bench_command


def _newest_backup_file(site_name: str) -> Optional[str]:
	backups_dir = os.path.join(get_bench_path(), "sites", site_name, "private", "backups")
	if not os.path.isdir(backups_dir):
		return None
	candidates = []
	for pattern in ("*.sql.gz", "*.tar", "*.tgz"):
		candidates.extend(glob.glob(os.path.join(backups_dir, pattern)))
	if not candidates:
		return None
	return max(candidates, key=os.path.getmtime)


def enqueue_site_backup(
	site_name: str,
	backup_type: str = "Manual",
	tenant_company: Optional[str] = None,
	run_sync: bool = False,
) -> str:
	"""Queue a backup job. Use run_sync=True inside another long job (e.g. pre-delete)."""
	site_name = (site_name or "").strip()
	if not tenant_company and site_name:
		tenant_company = frappe.db.get_value("Tenant Company", {"site_name": site_name}, "name")

	job = frappe.get_doc(
		{
			"doctype": "Tenant Backup Job",
			"tenant_company": tenant_company,
			"site_name": site_name,
			"backup_type": backup_type,
			"status": "Queued",
		}
	)
	job.insert(ignore_permissions=True)
	frappe.db.commit()

	if run_sync or backup_type == "Pre-Delete":
		_run_backup_job(job.name)
		return job.name

	enqueue_kwargs = {
		"queue": "long",
		"timeout": 3600,
		"job_name": f"superadmin-backup-{job.name}",
		"job_doc_name": job.name,
	}
	try:
		frappe.enqueue("superadmin.backup._run_backup_job", **enqueue_kwargs)
	except TypeError:
		frappe.enqueue(
			"superadmin.backup._run_backup_job",
			queue="long",
			timeout=3600,
			job_doc_name=job.name,
		)
	return job.name


def _run_backup_job(job_doc_name: str) -> None:
	job = frappe.get_doc("Tenant Backup Job", job_doc_name)
	site_name = (job.site_name or "").strip()
	job.status = "Running"
	job.started_on = now_datetime()
	job.save(ignore_permissions=True)
	frappe.db.commit()

	bench = find_bench_executable()
	cwd = get_bench_path()
	cmd = [bench, "--site", site_name, "backup", "--with-files"]

	try:
		log = _run_bench_command(cmd, cwd, timeout=3600)
		path = _newest_backup_file(site_name)
		job.reload()
		job.status = "Success"
		job.file_path = path or ""
		job.log = (log or "")[-65000:]
		job.finished_on = now_datetime()
		job.save(ignore_permissions=True)
		frappe.db.commit()
		audit.log_action("backup_success", "Tenant Backup Job", job.name, site_name)
	except Exception as e:
		job.reload()
		job.status = "Failed"
		job.log = (str(e) + "\n" + (frappe.get_traceback() or ""))[-65000:]
		job.finished_on = now_datetime()
		job.save(ignore_permissions=True)
		frappe.db.commit()
		audit.log_action("backup_failed", "Tenant Backup Job", job.name, site_name)
		from superadmin import notifications

		notifications.notify_event(
			"backup_failed",
			{"site_name": site_name, "job": job.name, "error": str(e)},
		)
		raise


def wait_for_backup(job_name: str, timeout: int = 1800) -> bool:
	deadline = time.time() + max(30, timeout)
	while time.time() < deadline:
		status = frappe.db.get_value("Tenant Backup Job", job_name, "status")
		if status == "Success":
			return True
		if status == "Failed":
			return False
		time.sleep(5)
	return False


def enqueue_scheduled_backups() -> None:
	"""Daily: backup all active tenants, then prune old backups by retention days."""
	rows = frappe.get_all(
		"Tenant Company",
		filters={"status": "Active", "company_access": "Active"},
		fields=["name", "site_name"],
	)
	for row in rows:
		site = (row.site_name or "").strip()
		if not site:
			continue
		try:
			enqueue_site_backup(site, backup_type="Scheduled", tenant_company=row.name)
		except Exception:
			frappe.log_error(title=f"superadmin scheduled backup {row.name}")
	try:
		prune_old_backups()
	except Exception:
		frappe.log_error(title="superadmin prune_old_backups")


def prune_old_backups() -> int:
	days = 14
	try:
		days = int(frappe.db.get_single_value("Superadmin Settings", "backup_retention_days") or 14)
	except Exception:
		pass
	days = max(1, min(days, 365))
	cutoff = time.time() - (days * 86400)
	removed = 0
	sites_root = os.path.join(get_bench_path(), "sites")
	for site in os.listdir(sites_root):
		bdir = os.path.join(sites_root, site, "private", "backups")
		if not os.path.isdir(bdir):
			continue
		for name in os.listdir(bdir):
			path = os.path.join(bdir, name)
			try:
				if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
					os.remove(path)
					removed += 1
			except OSError:
				pass
	return removed


@frappe.whitelist()
def request_site_backup(site_name: Optional[str] = None, tenant_company: Optional[str] = None):
	from superadmin.permissions import only_platform

	only_platform("Platform Admin", "Platform Ops")
	if not site_name and tenant_company:
		site_name = frappe.db.get_value("Tenant Company", tenant_company, "site_name")
	if not site_name:
		frappe.throw(_("Site Name is required"))
	job = enqueue_site_backup(site_name, backup_type="Manual", tenant_company=tenant_company)
	return {"ok": True, "job": job}


@frappe.whitelist()
def list_site_backups(site_name: Optional[str] = None):
	from superadmin.permissions import only_platform

	only_platform("Platform Admin", "Platform Ops")
	site_name = (site_name or "").strip()
	if not site_name:
		frappe.throw(_("Site Name is required"))
	bdir = os.path.join(get_bench_path(), "sites", site_name, "private", "backups")
	if not os.path.isdir(bdir):
		return []
	out = []
	for name in sorted(os.listdir(bdir), reverse=True):
		path = os.path.join(bdir, name)
		if not os.path.isfile(path):
			continue
		out.append(
			{
				"name": name,
				"path": path,
				"size": os.path.getsize(path),
				"mtime": os.path.getmtime(path),
			}
		)
	return out[:100]


@frappe.whitelist()
def restore_site_backup(site_name: Optional[str] = None, backup_file: Optional[str] = None):
	from superadmin.permissions import only_platform

	only_platform("Platform Admin")
	if not frappe.conf.get("superadmin_allow_restore"):
		frappe.throw(
			_(
				"Restore is disabled. Set superadmin_allow_restore in site_config after approving a restore window."
			)
		)
	site_name = (site_name or "").strip()
	backup_file = (backup_file or "").strip()
	if not site_name or not backup_file:
		frappe.throw(_("Site Name and backup file are required"))
	bdir = os.path.realpath(os.path.join(get_bench_path(), "sites", site_name, "private", "backups"))
	full = os.path.realpath(backup_file if os.path.isabs(backup_file) else os.path.join(bdir, backup_file))
	if not full.startswith(bdir + os.sep) or not os.path.isfile(full):
		frappe.throw(_("Invalid backup file path"))

	lab = frappe.conf.get("superadmin_restore_lab_site") or f"restore-lab.{site_name}"
	audit.log_action("restore_requested", "Tenant Company", site_name, f"file={full}; lab={lab}")
	bench = find_bench_executable()
	return {
		"ok": True,
		"message": _(
			"Backup validated. Restore onto lab site `{0}` with bench restore after approval; live overwrite is not automated."
		).format(lab),
		"backup_file": full,
		"lab_site": lab,
		"hint_cmd": f"{bench} --site {lab} restore {full}",
	}
