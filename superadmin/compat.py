"""Cross-version helpers for Frappe / ERPNext / Docker bench stacks."""

from __future__ import annotations

import os
import re
import shutil
from typing import Any, Callable, List, Optional, Sequence, Tuple

import frappe
from frappe import _
from frappe.utils import get_bench_path

_VERSION_RE = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")


def parse_version(value: Optional[str]) -> Tuple[int, int, int]:
	if not value:
		return (0, 0, 0)
	match = _VERSION_RE.search(str(value))
	if not match:
		return (0, 0, 0)
	major, minor, patch = match.groups()
	return (int(major), int(minor), int(patch or 0))


def frappe_version() -> Tuple[int, int, int]:
	return parse_version(getattr(frappe, "__version__", None) or "")


def version_at_least(minimum: str) -> bool:
	return frappe_version() >= parse_version(minimum)


def is_docker_bench() -> bool:
	"""Heuristic: official frappe_docker images and common container markers."""
	if os.path.exists("/.dockerenv"):
		return True
	if os.environ.get("FRAPPE_DOCKER") or os.environ.get("BENCH_DIR"):
		return True
	bench = get_bench_path()
	# Production images keep apps in-image and sites on a volume.
	return os.path.isdir(os.path.join(bench, "apps", "frappe")) and os.path.isdir(
		os.path.join(bench, "sites")
	)


def app_installed(app_name: str) -> bool:
	try:
		return app_name in (frappe.get_installed_apps() or [])
	except Exception:
		return False


def app_on_bench(app_name: str) -> bool:
	return os.path.isdir(os.path.join(get_bench_path(), "apps", app_name))


def default_tenant_apps() -> List[str]:
	"""Prefer ERPNext when present on the bench; otherwise install nothing extra by default."""
	if app_on_bench("erpnext"):
		return ["erpnext"]
	return []


def find_bench_executable() -> str:
	path = shutil.which("bench")
	if path:
		return path
	candidate = os.path.join(get_bench_path(), "env", "bin", "bench")
	if os.path.isfile(candidate):
		return candidate
	# Some images expose a wrapper at /usr/local/bin/bench only.
	for candidate in ("/usr/local/bin/bench", "/usr/bin/bench"):
		if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
			return candidate
	frappe.throw(_("Could not find `bench` on PATH or in bench/env/bin."))


def init_site(site_name: str) -> None:
	"""frappe.init changed keyword usage across versions; try safe variants."""
	try:
		frappe.init(site=site_name)
		return
	except TypeError:
		pass
	frappe.init(site_name)


def connect_site(site_name: str) -> None:
	init_site(site_name)
	frappe.connect()


def with_site(site_name: str, fn: Callable[[], Any]) -> Any:
	"""Run callable inside another site context, then restore the caller site.

	Preserves HTTP request/session bits so desk `savedocs` can still commit after
	tenant-site work (frappe.destroy() would otherwise drop frappe.local.request).
	"""
	management_site = getattr(getattr(frappe, "local", None), "site", None)
	saved_request = getattr(frappe.local, "request", None)
	saved_form_dict = getattr(frappe.local, "form_dict", None)
	saved_user = None
	try:
		saved_user = frappe.session.user
	except Exception:
		saved_user = None
	saved_flags = {}
	try:
		saved_flags = dict(frappe.local.flags or {})
	except Exception:
		saved_flags = {}

	frappe.destroy()
	try:
		connect_site(site_name)
		return fn()
	finally:
		frappe.destroy()
		if management_site:
			connect_site(management_site)
			if saved_request is not None:
				frappe.local.request = saved_request
			if saved_form_dict is not None:
				frappe.local.form_dict = saved_form_dict
			try:
				frappe.local.flags.update(saved_flags)
			except Exception:
				pass
			if saved_user:
				try:
					frappe.set_user(saved_user)
				except Exception:
					pass


def new_site_extra_args() -> List[str]:
	"""CLI flags that improve Docker / remote MariaDB compatibility without breaking classic benches."""
	args: List[str] = []
	# Remote DB in containers usually needs TCP + host login scope.
	if is_docker_bench() or os.environ.get("DB_HOST") or frappe.conf.get("db_host"):
		args.extend(["--no-mariadb-socket", "--mariadb-user-host-login-scope=%"])
	# Prefer verbose logs when available (ignored if unsupported).
	args.append("--verbose")
	return args


def filter_supported_bench_args(cmd: Sequence[str]) -> List[str]:
	"""Drop unknown flags on older bench CLIs by probing help text once."""
	bench = cmd[0] if cmd else "bench"
	try:
		import subprocess

		help_text = subprocess.run(
			[bench, "new-site", "--help"],
			cwd=get_bench_path(),
			text=True,
			capture_output=True,
			timeout=60,
			check=False,
		)
		text = (help_text.stdout or "") + (help_text.stderr or "")
	except Exception:
		return list(cmd)

	supported = list(cmd)
	optional_flags = {
		"--no-mariadb-socket": "--no-mariadb-socket" in text,
		"--mariadb-user-host-login-scope": "--mariadb-user-host-login-scope" in text,
		"--verbose": "--verbose" in text,
	}
	out: List[str] = []
	skip_next = False
	for i, arg in enumerate(supported):
		if skip_next:
			skip_next = False
			continue
		drop = False
		for flag, ok in optional_flags.items():
			if arg == flag or arg.startswith(flag + "="):
				if not ok:
					drop = True
					if arg == flag and flag == "--mariadb-user-host-login-scope":
						skip_next = True
				break
		if not drop:
			out.append(arg)
	return out
