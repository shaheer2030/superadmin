import frappe
from frappe import _
from frappe.model.document import Document


class TenantCompany(Document):
	def validate(self):
		self.set_hosts_file_entry()
		self.set_hosts_instructions()

	def set_hosts_file_entry(self):
		ip = (self.server_ip or "").strip()
		site = (self.site_name or "").strip()
		if ip and site:
			# Same format as Windows hosts: IP hostname (space-separated)
			self.hosts_file_entry = f"{ip} {site}"
		else:
			self.hosts_file_entry = ""

	def set_hosts_instructions(self):
		site = (self.site_name or "company1.local").strip()
		self.hosts_instructions = _(
			"Add the Hosts File Entry line to C:\\Windows\\System32\\drivers\\etc\\hosts, then open http://{0}"
		).format(site)
