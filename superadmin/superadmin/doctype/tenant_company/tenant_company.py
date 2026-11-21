import frappe
from frappe import _
from frappe.model.document import Document


class TenantCompany(Document):
	def before_insert(self):
		self.apply_superadmin_defaults()

	def validate(self):
		self.expand_site_name_from_settings()
		if self.install_apps is not None:
			self.install_apps = self.install_apps.strip()
		self.set_hosts_file_entry()
		self.set_hosts_instructions()

	def expand_site_name_from_settings(self):
		from superadmin.superadmin.doctype.superadmin_settings.superadmin_settings import expand_site_name

		if self.site_name:
			self.site_name = expand_site_name(self.site_name)

	def apply_superadmin_defaults(self):
		"""Fill Server IP / Install apps from Superadmin Settings when empty."""
		try:
			from superadmin.superadmin.doctype.superadmin_settings.superadmin_settings import (
				get_default_install_apps,
				get_default_server_ip,
			)
		except Exception:
			return

		if not (self.server_ip or "").strip():
			default_ip = get_default_server_ip()
			if default_ip:
				self.server_ip = default_ip

		if not (self.install_apps or "").strip():
			default_apps = get_default_install_apps()
			if default_apps:
				self.install_apps = default_apps

	def on_trash(self):
		if not getattr(frappe.local, "superadmin_allow_tenant_delete", False):
			frappe.throw(
				_(
					"لا يمكن حذف السجل مباشرة. استخدم زر <b>Delete company permanently</b> "
					"لحذف الموقع وقاعدة البيانات وSSL ثم السجل بشكل كامل."
				),
				title=_("Full tenant delete required"),
			)

	def set_hosts_file_entry(self):
		ip = (self.server_ip or "").strip()
		site = (self.site_name or "").strip()
		if ip and site:
			self.hosts_file_entry = f"{ip} {site}"
		else:
			self.hosts_file_entry = ""

	def set_hosts_instructions(self):
		site = (self.site_name or "company1.local").strip()
		self.hosts_instructions = _(
			"Add the Hosts File Entry line to C:\\Windows\\System32\\drivers\\etc\\hosts, then open http://{0}"
		).format(site)
