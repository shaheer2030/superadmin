// Copyright (c) 2026, Superadmin and contributors
// For license information, please see license.txt

frappe.ui.form.on("System Branding", {
	apply_to_all_tenants(frm) {
		frappe.confirm(
			__("سيتم تطبيق اسم النظام والشعار والأيقونة على كل مواقع الشركات النشطة. المتابعة؟"),
			() => {
				frm.call({
					method: "superadmin.superadmin.doctype.system_branding.system_branding.apply_branding_to_all_tenants",
					freeze: true,
					freeze_message: __("جارٍ التطبيق..."),
					callback(r) {
						const m = r.message || {};
						frappe.msgprint({
							title: __("تم"),
							indicator: "green",
							message: __(
								"طُبّق على {0} موقعًا. فشل: {1}",
								[(m.ok || []).length, (m.failed || []).length]
							),
						});
					},
				});
			}
		);
	},
});
