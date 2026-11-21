frappe.ui.form.on("Tenant Company", {
	onload(frm) {
		load_base_domain(frm).then(() => {
			update_site_name_preview(frm);
			if (frm.is_new()) apply_settings_defaults(frm);
		});
	},

	site_name(frm) {
		update_site_name_preview(frm);
	},

	refresh(frm) {
		frm.set_intro(null);
		render_progress(frm);

		if (frm.is_new()) {
			frm.set_intro(
				__(
					"Fill all required fields and click **Save**. Then use the **Create Site** button — **Provisioning** is not a button; status and log appear in the section below after the job runs."
				),
				"blue"
			);
			return;
		}

		const st = frm.doc.status;
		if (st === "Draft") {
			frm.set_intro(
				__(
					"Click **Create Site** (toolbar button). Ensure **`bench worker`** is running on the server or the job will stay queued with an empty log."
				),
				"blue"
			);
		} else if (st === "Queued" || st === "Provisioning") {
			frm.set_intro(
				__(
					"Provisioning is running in the background. **Reload** this document after a few minutes to see **Status** and **Provision Log**."
				),
				"orange"
			);
		} else if (st === "Deleting") {
			frm.set_intro(
				__(
					"<b>جاري الحذف النهائي</b><br>يتم حذف الموقع وقاعدة البيانات وSSL. حدّث الصفحة بعد قليل — سيختفي هذا السجل عند اكتمال الحذف."
				),
				"red"
			);
		} else if (st === "Failed") {
			frm.set_intro(__("Provisioning failed. Read **Provision Log** below, fix the issue, then try **Create Site** again."), "red");
		} else if (st === "Active") {
			if ((frm.doc.company_access || "Active") === "Suspended") {
				frm.set_intro(
					__(
						"<b>الشركة موقوفة حاليًا</b><br>زوار الموقع يرون صفحة «تم إيقاف وصول هذه الشركة» وليس شاشة النظام.<br>لإعادة الفتح: اضغط <b>Activate company</b> من شريط الأدوات."
					),
					"orange"
				);
			} else {
				frm.set_intro(
					__(
						"Site was created. Open <b>{0}</b> for the company desk. Use <b>Suspend company</b> to block visitor access with a clear suspended page."
					).replace("{0}", frappe.utils.escape_html(frm.doc.site_name || "")),
					"green"
				);
			}
		}

		if (["Queued", "Provisioning", "Deleting"].includes(st)) {
			setup_auto_reload(frm);
		}

		if (st === "Deleting") {
			return;
		}

		if (st === "Active") {
			if ((frm.doc.company_access || "Active") !== "Suspended") {
				frm.add_custom_button(__("Suspend company"), () => {
					frappe.confirm(
						__(
							"إيقاف الشركة؟<br><br>سيُمنع الدخول إلى <b>{0}</b> وستظهر للزوار صفحة واضحة بأن الشركة موقوفة (بدل رسالة Updating)."
						).replace("{0}", frappe.utils.escape_html(frm.doc.site_name || "")),
						() => {
							frappe.call({
								method: "superadmin.tenant_access.suspend_tenant_company",
								args: { docname: frm.doc.name },
								freeze: true,
								freeze_message: __("جارٍ إيقاف وصول الشركة…"),
								callback(r) {
									if (!r.exc) {
										frappe.show_alert({
											message: __("تم إيقاف الشركة. الزوار يرون صفحة التعليق الآن."),
											indicator: "orange",
										});
										frm.reload_doc();
									}
								},
							});
						}
					);
				});
			} else {
				frm.add_custom_button(__("Activate company"), () => {
					frappe.confirm(
						__("إعادة تفعيل الشركة وفتح الوصول إلى {0}؟", [frm.doc.site_name || ""]),
						() => {
							frappe.call({
								method: "superadmin.tenant_access.activate_tenant_company",
								args: { docname: frm.doc.name },
								freeze: true,
								freeze_message: __("جارٍ تفعيل الشركة…"),
								callback(r) {
									if (!r.exc) {
										frappe.show_alert({
											message: __("تم تفعيل الشركة. الموقع متاح للزوار."),
											indicator: "green",
										});
										frm.reload_doc();
									}
								},
							});
						}
					);
				});
			}
			add_delete_button(frm);
			return;
		}

		if (["Queued", "Provisioning"].includes(st)) {
			return;
		}

		// Draft / Failed: allow create + permanent delete (record / partial site)
		if (st !== "Active") {
			frm.add_custom_button(__("Create Site"), () => {
				frappe.call({
					method: "superadmin.api.create_tenant_site",
					args: { docname: frm.doc.name },
					freeze: true,
					freeze_message: __("Provisioning may take several minutes…"),
					callback(r) {
						if (!r.exc) {
							frappe.show_alert({
								message: __(
									"Job queued. Reload this document in a moment — Status should become Queued/Provisioning."
								),
								indicator: "blue",
							});
							frm.reload_doc();
						}
					},
				});
			});
			add_delete_button(frm);
		}
	},
});

function add_delete_button(frm) {
	const site = (frm.doc.site_name || "").trim();
	frm.add_custom_button(
		__("Delete company permanently"),
		() => {
			const d = new frappe.ui.Dialog({
				title: __("حذف نهائي للمستأجر"),
				fields: [
					{
						fieldtype: "HTML",
						options: `
							<div class="text-danger" style="margin-bottom:12px;line-height:1.6">
								<b>تحذير:</b> سيتم حذف الموقع وقاعدة البيانات وملف Nginx وشهادة SSL وسجل Tenant Company
								بشكل نهائي ولا يمكن التراجع عنه.
								<br><br>
								اكتب اسم الموقع للتأكيد:
								<code>${frappe.utils.escape_html(site)}</code>
							</div>`,
					},
					{
						label: __("Confirm Site Name"),
						fieldname: "confirm_site_name",
						fieldtype: "Data",
						reqd: 1,
					},
				],
				primary_action_label: __("Delete forever"),
				primary_action(values) {
					if ((values.confirm_site_name || "").trim().toLowerCase() !== site.toLowerCase()) {
						frappe.msgprint(__("Site Name confirmation does not match."));
						return;
					}
					d.hide();
					frappe.call({
						method: "superadmin.api.delete_tenant_company",
						args: {
							docname: frm.doc.name,
							confirm_site_name: values.confirm_site_name,
						},
						freeze: true,
						freeze_message: __("جارٍ بدء الحذف النهائي…"),
						callback(r) {
							if (!r.exc) {
								frappe.show_alert({
									message: __("Delete job queued. This document will disappear when finished."),
									indicator: "red",
								});
								frm.reload_doc();
							}
						},
					});
				},
			});
			d.show();
		},
		__("Danger")
	);
}

function render_progress(frm) {
	const field = frm.fields_dict.progress_bar;
	if (!field) return;

	const percent = cint(frm.doc.progress_percent || 0);
	const stage = frm.doc.progress_stage || frm.doc.status || __("Draft");
	const status = frm.doc.status || "Draft";
	const access = frm.doc.company_access || "Active";
	const color =
		status === "Deleting"
			? "var(--red-500)"
			: status === "Active" && access === "Suspended"
			? "var(--orange-500)"
			: status === "Active"
			? "var(--green-500)"
			: status === "Failed"
			? "var(--red-500)"
			: "var(--blue-500)";

	field.$wrapper.html(`
		<div style="margin-bottom: 12px;">
			<div class="flex justify-between text-muted small" style="margin-bottom: 6px;">
				<span>${frappe.utils.escape_html(stage)}</span>
				<span>${percent}%</span>
			</div>
			<div style="height: 12px; background: var(--control-bg); border-radius: 999px; overflow: hidden;">
				<div
					style="
						width: ${percent}%;
						height: 100%;
						background: ${color};
						transition: width 0.4s ease;
					"
				></div>
			</div>
		</div>
	`);
}

function setup_auto_reload(frm) {
	if (frm._superadmin_progress_reload) return;
	frm._superadmin_progress_reload = setInterval(() => {
		if (!["Queued", "Provisioning", "Deleting"].includes(frm.doc.status)) {
			clearInterval(frm._superadmin_progress_reload);
			frm._superadmin_progress_reload = null;
			return;
		}
		frm.reload_doc().catch(() => {
			// Document deleted — go back to list
			clearInterval(frm._superadmin_progress_reload);
			frm._superadmin_progress_reload = null;
			frappe.set_route("List", "Tenant Company");
			frappe.show_alert({ message: __("تم حذف الشركة نهائيًا."), indicator: "green" });
		});
	}, 7000);
}

function load_base_domain(frm) {
	return frappe.db
		.get_single_value("Superadmin Settings", "base_domain")
		.then((domain) => {
			frm._superadmin_base_domain = (domain || "").trim().toLowerCase().replace(/\.+$/, "");
			return frm._superadmin_base_domain;
		})
		.catch(() => {
			frm._superadmin_base_domain = "";
			return "";
		});
}

function update_site_name_preview(frm) {
	const raw = (frm.doc.site_name || "").trim().toLowerCase().replace(/\.+$/, "");
	const domain = frm._superadmin_base_domain || "";
	let hint =
		__("Type subdomain only (e.g. alnoor) — becomes alnoor.<Base Domain> from Superadmin Settings. Full FQDN still accepted.");
	if (raw && domain && !raw.includes(".")) {
		hint = __("Full site name will be: <b>{0}.{1}</b>", [frappe.utils.escape_html(raw), frappe.utils.escape_html(domain)]);
	} else if (raw && raw.includes(".")) {
		hint = __("Using full Site Name: <b>{0}</b>", [frappe.utils.escape_html(raw)]);
	} else if (domain) {
		hint = __("Base Domain is <b>{0}</b> — type e.g. <code>alnoor</code> → <code>alnoor.{0}</code>", [frappe.utils.escape_html(domain)]);
	}
	frm.set_df_property("site_name", "description", hint);
}

function apply_settings_defaults(frm) {
	frappe.db
		.get_doc("Superadmin Settings")
		.then((s) => {
			if (!s) return;
			frm._superadmin_base_domain = (s.base_domain || "").trim().toLowerCase().replace(/\.+$/, "");
			if (!frm.doc.server_ip && s.default_server_ip) {
				frm.set_value("server_ip", s.default_server_ip);
			}
			if (!(frm.doc.install_apps || "").trim() && s.default_install_apps) {
				frm.set_value("install_apps", s.default_install_apps);
			}
			update_site_name_preview(frm);
		})
		.catch(() => {});
}

