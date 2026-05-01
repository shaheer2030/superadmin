frappe.ui.form.on("Tenant Company", {
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
		} else if (st === "Failed") {
			frm.set_intro(__("Provisioning failed. Read **Provision Log** below, fix the issue, then try **Create Site** again."), "red");
		} else if (st === "Active") {
			frm.set_intro(__("Site was created. Use **Hosts File Entry** below on client PCs."), "green");
		}

		if (["Queued", "Provisioning"].includes(st)) {
			setup_auto_reload(frm);
		}

		if (["Active", "Queued", "Provisioning"].includes(st)) {
			return;
		}

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
	},
});

function render_progress(frm) {
	const field = frm.fields_dict.progress_bar;
	if (!field) return;

	const percent = cint(frm.doc.progress_percent || 0);
	const stage = frm.doc.progress_stage || frm.doc.status || __("Draft");
	const status = frm.doc.status || "Draft";
	const color =
		status === "Active"
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
		if (!["Queued", "Provisioning"].includes(frm.doc.status)) {
			clearInterval(frm._superadmin_progress_reload);
			frm._superadmin_progress_reload = null;
			return;
		}
		frm.reload_doc();
	}, 7000);
}
