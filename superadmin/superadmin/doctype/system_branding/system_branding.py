# Copyright (c) 2026, Superadmin and contributors
# For license information, please see license.txt

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_bench_path, get_url


class SystemBranding(Document):
	def validate(self):
		self.system_name = (self.system_name or "").strip() or "ORACPC"

	def on_update(self):
		logo_url, favicon_url = sync_branding_assets(self)
		apply_branding_to_current_site(
			system_name=self.system_name,
			logo_url=logo_url,
			favicon_url=favicon_url,
		)
		try:
			frappe.clear_cache()
		except Exception:
			pass


def _branding_dest_dirs() -> list[Path]:
	"""Writable destinations for shared branding assets (dedupe symlink targets)."""
	bench = Path(get_bench_path())
	candidates = [
		bench / "sites/assets/superadmin/images/branding",
		bench / "apps/superadmin/superadmin/public/images/branding",
	]
	seen = set()
	out: list[Path] = []
	for path in candidates:
		try:
			key = path.resolve()
		except OSError:
			key = path
		if key in seen:
			continue
		seen.add(key)
		out.append(path)
	return out


def _safe_copy_file(src: Path, dest: Path) -> None:
	"""Copy without failing on SameFileError / chmod-on-bind-mount."""
	dest.parent.mkdir(parents=True, exist_ok=True)
	try:
		if dest.exists() and src.resolve() == dest.resolve():
			return
	except OSError:
		pass
	tmp = dest.with_name(dest.name + ".tmp")
	try:
		shutil.copyfile(src, tmp)
		os.replace(tmp, dest)
	except Exception:
		if tmp.exists():
			try:
				tmp.unlink()
			except OSError:
				pass
		raise
	try:
		os.chmod(dest, 0o664)
	except OSError:
		pass



def _local_file_from_attach(attach: str) -> Optional[Path]:
	"""Resolve an Attach/Attach Image value to a readable local path on this site."""
	if not attach:
		return None
	value = unquote((attach or "").strip())
	# Ignore File doctype wrapper noise
	if value in ("", "attach_files:"):
		return None

	site_path = Path(frappe.get_site_path())
	candidates = []

	parsed = urlparse(value)
	path = parsed.path if parsed.scheme else value
	path = path.split("?")[0]

	if path.startswith("/files/"):
		candidates.append(site_path / "public" / path.lstrip("/"))
		candidates.append(site_path / "private" / path.lstrip("/"))
		# File may be stored under private/files even when URL is /files/
		candidates.append(site_path / "private/files" / Path(path).name)
		candidates.append(site_path / "public/files" / Path(path).name)
	elif path.startswith("/private/files/") or path.startswith("/public/files/"):
		candidates.append(site_path / path.lstrip("/"))
	elif path.startswith("/assets/superadmin/images/branding/"):
		candidates.append(Path(get_bench_path()) / "sites" / path.lstrip("/"))
		candidates.append(Path(get_bench_path()) / "apps/superadmin/superadmin/public/images/branding" / Path(path).name)
	elif not path.startswith("/"):
		# relative files/name
		candidates.append(site_path / "public" / path)
		candidates.append(site_path / "private" / path)

	for cand in candidates:
		try:
			if cand.is_file():
				return cand
		except OSError:
			continue
	return None


def _copy_attach_to_asset(attach: str, dest_stem: str) -> Optional[str]:
	"""Copy uploaded file into shared assets; return public URL usable by all tenants."""
	if attach and str(attach).startswith("/assets/superadmin/images/branding/"):
		return str(attach).split("?")[0]

	src = _local_file_from_attach(attach)
	if not src or not src.is_file():
		frappe.log_error(
			message=f"Could not resolve branding attach path: {attach!r}",
			title="system_branding missing source file",
		)
		return None

	ext = src.suffix.lower() or ".png"
	if ext not in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".svgz"):
		ext = ".png"
	filename = f"{dest_stem}{ext}"

	written = None
	errors = []
	for dest_dir in _branding_dest_dirs():
		try:
			dest = dest_dir / filename
			_safe_copy_file(src, dest)
			written = dest
			break
		except OSError as e:
			errors.append(f"{dest_dir}: {e}")
			continue

	if not written:
		# Fall back to an already-published shared asset if present
		for dest_dir in _branding_dest_dirs():
			existing = dest_dir / filename
			if existing.is_file():
				return f"/assets/superadmin/images/branding/{filename}"
		frappe.throw(
			_("Permission denied while saving branding file. Checked: {0}").format(" | ".join(errors))
		)

	# Mirror into other destinations when possible (best-effort)
	for dest_dir in _branding_dest_dirs():
		try:
			dest = dest_dir / filename
			if dest.resolve() != written.resolve():
				_safe_copy_file(written, dest)
		except OSError:
			pass

	return f"/assets/superadmin/images/branding/{filename}"


def sync_branding_assets(doc=None) -> tuple[Optional[str], Optional[str]]:
	doc = doc or frappe.get_single("System Branding")
	logo_url = _copy_attach_to_asset(doc.system_logo, "system-logo") if doc.system_logo else None
	favicon_url = _copy_attach_to_asset(doc.favicon, "favicon") if doc.favicon else None
	return logo_url, favicon_url


DESK_BRANDING_JS = "/assets/superadmin/js/desk_branding.js"
SETUP_WIZARD_SAAS_JS = "/assets/superadmin/js/setup_wizard_saas.js"

# Injected on every tenant (and management) via site_config — apps need not be installed.
_TENANT_DESK_JS = (
	DESK_BRANDING_JS,
	SETUP_WIZARD_SAAS_JS,
)


def ensure_desk_branding_js_include() -> None:
	"""Load desk logo + SaaS setup-wizard patches on sites that do not install superadmin.

	Frappe merges site_config.app_include_js with installed-app hooks (desk.py).
	"""
	from frappe.installer import update_site_config

	current = frappe.conf.get("app_include_js") or []
	if isinstance(current, str):
		current = [current]
	elif not isinstance(current, list):
		current = list(current)

	changed = False
	for path in _TENANT_DESK_JS:
		if path not in current:
			current = list(current) + [path]
			changed = True
	if changed:
		update_site_config("app_include_js", current)
		frappe.conf.app_include_js = current


def ensure_tenant_saas_js(site_name: str) -> None:
	"""Ensure setup_wizard_saas.js (+ branding js) is in tenant site_config.app_include_js."""
	from superadmin.compat import with_site

	site_name = (site_name or "").strip()
	if not site_name:
		return

	def _inner():
		ensure_desk_branding_js_include()

	with_site(site_name, _inner)


def apply_branding_to_current_site(
	system_name: Optional[str] = None,
	logo_url: Optional[str] = None,
	favicon_url: Optional[str] = None,
) -> None:
	"""Apply branding on the site currently connected in frappe."""
	system_name = (system_name or "").strip() or "ORACPC"

	# Website Settings: app name + logo + favicon
	ws = frappe.get_single("Website Settings")
	ws.app_name = system_name
	if logo_url:
		ws.app_logo = logo_url
		if hasattr(ws, "splash_image"):
			ws.splash_image = logo_url
	if favicon_url:
		ws.favicon = favicon_url
	ws.save(ignore_permissions=True)

	# Navbar Settings: desk sidebar logo
	try:
		nb = frappe.get_single("Navbar Settings")
		if logo_url:
			nb.app_logo = logo_url
			nb.save(ignore_permissions=True)
	except Exception:
		frappe.log_error(title="system_branding navbar")

	# System Settings app_name when present
	try:
		if frappe.db.exists("DocType", "System Settings"):
			ss = frappe.get_single("System Settings")
			if hasattr(ss, "app_name"):
				ss.app_name = system_name
				ss.save(ignore_permissions=True)
	except Exception:
		pass

	# Setup wizard + desk logo override without installing superadmin on tenants
	try:
		ensure_desk_branding_js_include()
	except Exception:
		frappe.log_error(title="system_branding desk js include")

	frappe.clear_cache()
	frappe.db.commit()


def get_branding_values() -> dict:
	try:
		doc = frappe.get_single("System Branding")
	except Exception:
		return {"system_name": "ORACPC", "logo_url": None, "favicon_url": None}
	logo_url, favicon_url = sync_branding_assets(doc)
	return {
		"system_name": (doc.system_name or "ORACPC").strip(),
		"logo_url": logo_url or doc.system_logo,
		"favicon_url": favicon_url or doc.favicon,
		"apply_to_new_tenants": 1 if doc.apply_to_new_tenants else 0,
	}


def apply_branding_to_site(site_name: str) -> None:
	from superadmin.compat import with_site

	values = get_branding_values()

	def _inner():
		apply_branding_to_current_site(
			system_name=values["system_name"],
			logo_url=values.get("logo_url"),
			favicon_url=values.get("favicon_url"),
		)

	with_site(site_name, _inner)


@frappe.whitelist()
def apply_branding_to_all_tenants():
	frappe.only_for("System Manager")
	# Ensure assets synced from current System Branding first
	doc = frappe.get_single("System Branding")
	sync_branding_assets(doc)
	apply_branding_to_current_site(
		system_name=doc.system_name,
		logo_url=_copy_attach_to_asset(doc.system_logo, "system-logo") if doc.system_logo else None,
		favicon_url=_copy_attach_to_asset(doc.favicon, "favicon") if doc.favicon else None,
	)

	sites = frappe.get_all(
		"Tenant Company",
		filters={"status": "Active"},
		pluck="site_name",
	)
	ok, failed = [], []
	for site in sites:
		if not site or site in ("oracpc.tech", "www.oracpc.tech"):
			continue
		try:
			apply_branding_to_site(site)
			ok.append(site)
		except Exception:
			failed.append({"site": site, "error": frappe.get_traceback()})
			frappe.log_error(title=f"branding apply failed: {site}")
	return {"ok": ok, "failed": [f["site"] for f in failed], "failed_detail": failed}
