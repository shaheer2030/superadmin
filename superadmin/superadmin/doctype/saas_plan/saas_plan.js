// Copyright (c) 2026, Superadmin and contributors
// For license information, please see license.txt

frappe.ui.form.on("SaaS Plan", {
	refresh(frm) {
		frm.add_custom_button(__("اختر الوحدات"), () => open_module_picker(frm), __("الباقة"));
		frm.add_custom_button(__("اختر التطبيقات"), () => open_app_picker(frm), __("الباقة"));
		frm.add_custom_button(__("مزامنة الوحدات من التطبيقات"), () => {
			sync_modules_from_plan_apps(frm, { prune: true });
		}, __("الباقة"));
		frm.add_custom_button(__("تعبئة الوحدات الافتراضية"), () => {
			if ((frm.doc.plan_modules || []).length) {
				frappe.confirm(__("Replace existing plan modules?"), () => fill_default_modules(frm));
			} else {
				fill_default_modules(frm);
			}
		}, __("الباقة"));
		load_app_name_select_options(frm);
		load_module_name_select_options(frm);
	},
	plan_apps_remove(frm) {
		prune_modules_not_in_plan_apps(frm);
	},
});

frappe.ui.form.on("SaaS Plan App", {
	app_name(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.app_name && !row.app_label) {
			frappe.model.set_value(cdt, cdn, "app_label", row.app_name);
		}
		if (row.app_name) {
			add_modules_for_app(frm, row.app_name);
		}
	},
});

frappe.ui.form.on("SaaS Plan Module", {
	module_name(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.module_name) {
			return;
		}
		frappe.call({
			method: "superadmin.entitlements.get_module_meta",
			args: { module_name: row.module_name },
			callback(r) {
				const meta = r.message || {};
				if (meta.module_label) {
					frappe.model.set_value(cdt, cdn, "module_label", meta.module_label);
				}
				if (meta.source_app) {
					frappe.model.set_value(cdt, cdn, "source_app", meta.source_app);
				}
			},
		});
	},
});

function load_app_name_select_options(frm) {
	frappe.call({
		method: "superadmin.entitlements.get_installable_app_options",
		callback(r) {
			const options = r.message || "";
			if (!options.trim()) {
				return;
			}
			const grid = frm.fields_dict.plan_apps && frm.fields_dict.plan_apps.grid;
			if (!grid) {
				return;
			}
			grid.update_docfield_property("app_name", "options", options);
			frm.refresh_field("plan_apps");
		},
	});
}

function load_module_name_select_options(frm) {
	frappe.call({
		method: "superadmin.entitlements.get_plan_module_options",
		callback(r) {
			const options = r.message || "";
			if (!options.trim()) {
				return;
			}
			const grid = frm.fields_dict.plan_modules && frm.fields_dict.plan_modules.grid;
			if (!grid) {
				return;
			}
			grid.update_docfield_property("module_name", "options", options);
			frm.refresh_field("plan_modules");
		},
	});
}

function plan_app_names(frm) {
	const names = [];
	(frm.doc.plan_apps || []).forEach((row) => {
		if (row.app_name && names.indexOf(row.app_name) === -1) {
			names.push(row.app_name);
		}
	});
	return names;
}

function add_modules_for_app(frm, app_name) {
	if (!app_name) {
		return;
	}
	frappe.call({
		method: "superadmin.entitlements.get_modules_for_apps",
		args: { apps: [app_name] },
		callback(r) {
			const modules = r.message || [];
			if (!modules.length) {
				frappe.show_alert({
					message: __("لا توجد وحدات معروفة للتطبيق {0}", [app_name]),
					indicator: "orange",
				});
				return;
			}
			const have = current_module_map(frm);
			let added = 0;
			modules.forEach((m) => {
				if (have[m.module_name]) {
					return;
				}
				const row = frm.add_child("plan_modules");
				row.module_name = m.module_name;
				row.module_label = m.module_label || m.module_name;
				row.enabled = 1;
				row.source_app = m.source_app || app_name;
				added += 1;
			});
			frm.refresh_field("plan_modules");
			if (added) {
				frappe.show_alert({
					message: __("أُضيفت {0} وحدة من {1}", [added, app_name]),
					indicator: "green",
				});
				frm.dirty();
			}
		},
	});
}

function sync_modules_from_plan_apps(frm, opts) {
	const apps = plan_app_names(frm);
	if (!apps.length) {
		frappe.msgprint(__("أضف تطبيقاً أولاً في تطبيقات الباقة"));
		return;
	}
	frappe.call({
		method: "superadmin.entitlements.get_modules_for_apps",
		args: { apps },
		freeze: true,
		callback(r) {
			const modules = r.message || [];
			const have = current_module_map(frm);
			let added = 0;
			modules.forEach((m) => {
				if (have[m.module_name]) {
					return;
				}
				const row = frm.add_child("plan_modules");
				row.module_name = m.module_name;
				row.module_label = m.module_label || m.module_name;
				row.enabled = 1;
				row.source_app = m.source_app || "erpnext";
				added += 1;
			});
			frm.refresh_field("plan_modules");
			if (opts && opts.prune) {
				prune_modules_not_in_plan_apps(frm);
			}
			frappe.show_alert({
				message: __("مزامنة الوحدات: أُضيف {0}", [added]),
				indicator: "green",
			});
			if (added) {
				frm.dirty();
			}
		},
	});
}

function prune_modules_not_in_plan_apps(frm) {
	const apps = new Set(plan_app_names(frm));
	if (!apps.size) {
		return;
	}
	const keep = [];
	(frm.doc.plan_modules || []).forEach((row) => {
		const src = (row.source_app || "").trim();
		if (!src || apps.has(src)) {
			keep.push({
				module_name: row.module_name,
				module_label: row.module_label,
				enabled: row.enabled,
				source_app: row.source_app,
				notes: row.notes,
			});
		}
	});
	const removed = (frm.doc.plan_modules || []).length - keep.length;
	if (!removed) {
		return;
	}
	frm.clear_table("plan_modules");
	keep.forEach((m) => {
		const row = frm.add_child("plan_modules");
		row.module_name = m.module_name;
		row.module_label = m.module_label;
		row.enabled = m.enabled;
		row.source_app = m.source_app;
		row.notes = m.notes;
	});
	frm.refresh_field("plan_modules");
	frm.dirty();
	frappe.show_alert({
		message: __("أُزيلت {0} وحدة لتطبيقات غير موجودة في الباقة", [removed]),
		indicator: "orange",
	});
}

function current_module_map(frm) {
	const map = {};
	(frm.doc.plan_modules || []).forEach((row) => {
		if (row.module_name) {
			map[row.module_name] = row;
		}
	});
	return map;
}

function open_module_picker(frm) {
	frappe.call({
		method: "superadmin.entitlements.get_entitlement_catalog",
		args: { plan: frm.doc.name },
		freeze: true,
		freeze_message: __("Loading modules…"),
		callback(r) {
			const modules = (r.message && r.message.modules) || [];
			if (!modules.length) {
				frappe.msgprint(__("No modules found"));
				return;
			}
			const existing = current_module_map(frm);
			const fields = modules.map((m) => {
				const label = m.module_label && m.module_label !== m.module_name
					? `${m.module_label} — ${m.module_name}`
					: m.module_name;
				const app = m.source_app || "erpnext";
				const hint = existing[m.module_name] ? "" : ` (${__("غير مضمّنة")})`;
				return {
					fieldtype: "Check",
					fieldname: `mod__${frappe.scrub(m.module_name)}`,
					label: `${label} [${app}]${hint}`,
					default: existing[m.module_name] ? cint(existing[m.module_name].enabled) : 0,
					module_meta: m,
				};
			});

			const d = new frappe.ui.Dialog({
				title: __("اختيار وحدات ERPNext للباقة"),
				size: "large",
				fields: [
					{
						fieldtype: "HTML",
						options: `<p class="text-muted" style="margin-top:0">
							${__("حدّد الوحدات المسموحة في هذه الباقة. غير المحدد سيُحظر على مستوى الخادم (Module Profile + الأدوار).")}
							<br>${__("الوحدات غير المضمّنة حاليًا في الجدول تظهر بعلامة")} <b>${__("غير مضمّنة")}</b>.
						</p>
						<p>
							<a href="#" class="sa-mod-select-all">${__("تحديد الكل")}</a>
							&nbsp;|&nbsp;
							<a href="#" class="sa-mod-select-none">${__("إلغاء الكل")}</a>
							&nbsp;|&nbsp;
							<a href="#" class="sa-mod-select-missing">${__("إظهار غير المضمّنة فقط")}</a>
						</p>`,
					},
					{
						fieldtype: "Section Break",
						label: __("الوحدات"),
					},
					...fields,
				],
				primary_action_label: __("تطبيق على الباقة"),
				primary_action(values) {
					apply_module_selection(frm, modules, values);
					d.hide();
				},
			});
			d.show();

			d.$wrapper.on("click", ".sa-mod-select-all", (e) => {
				e.preventDefault();
				modules.forEach((m) => {
					d.set_value(`mod__${frappe.scrub(m.module_name)}`, 1);
				});
			});
			d.$wrapper.on("click", ".sa-mod-select-none", (e) => {
				e.preventDefault();
				modules.forEach((m) => {
					d.set_value(`mod__${frappe.scrub(m.module_name)}`, 0);
				});
			});
			d.$wrapper.on("click", ".sa-mod-select-missing", (e) => {
				e.preventDefault();
				d.$wrapper.find(".frappe-control[data-fieldname^='mod__']").each(function () {
					const $ctrl = $(this);
					const label = $ctrl.find(".control-label, label").text() || "";
					if (label.indexOf(__("غير مضمّنة")) === -1) {
						$ctrl.hide();
					} else {
						$ctrl.show();
					}
				});
			});
		},
	});
}

function apply_module_selection(frm, modules, values) {
	const selected = [];
	modules.forEach((m) => {
		const key = `mod__${frappe.scrub(m.module_name)}`;
		if (cint(values[key])) {
			selected.push(m);
		}
	});

	frm.clear_table("plan_modules");
	selected.forEach((m) => {
		const row = frm.add_child("plan_modules");
		row.module_name = m.module_name;
		row.module_label = m.module_label || m.module_name;
		row.enabled = 1;
		row.source_app = m.source_app || "erpnext";
	});
	frm.refresh_field("plan_modules");
	frappe.show_alert({
		message: __("تم اختيار {0} وحدة. احفظ الباقة لتطبيقها على المشتركين.", [selected.length]),
		indicator: "green",
	});
}

function open_app_picker(frm) {
	frappe.call({
		method: "superadmin.entitlements.get_entitlement_catalog",
		args: { plan: frm.doc.name },
		callback(r) {
			const apps = (r.message && r.message.apps) || [];
			if (!apps.length) {
				frappe.msgprint(__("No apps found on bench"));
				return;
			}
			const have = {};
			(frm.doc.plan_apps || []).forEach((row) => {
				if (row.app_name) have[row.app_name] = row;
			});
			const fields = apps.map((a) => ({
				fieldtype: "Check",
				fieldname: `app__${frappe.scrub(a.app_name)}`,
				label: `${a.app_label || a.app_name}${have[a.app_name] ? "" : ` (${__("غير مضمّن")})`}`,
				default: have[a.app_name] ? cint(have[a.app_name].install) : 0,
				app_meta: a,
			}));
			const d = new frappe.ui.Dialog({
				title: __("اختيار تطبيقات Frappe للتثبيت"),
				fields: [
					{
						fieldtype: "HTML",
						options: `<p class="text-muted">${__(
							"هذه تطبيقات مستقلة تُثبَّت على موقع العميل (مثل erpnext أو hrms)، وليست وحدات داخل ERPNext."
						)}</p>`,
					},
					...fields,
				],
				primary_action_label: __("تطبيق"),
				primary_action(values) {
					frm.clear_table("plan_apps");
					apps.forEach((a) => {
						if (cint(values[`app__${frappe.scrub(a.app_name)}`])) {
							const row = frm.add_child("plan_apps");
							row.app_name = a.app_name;
							row.app_label = a.app_label || a.app_name;
							row.install = 1;
						}
					});
					frm.refresh_field("plan_apps");
					d.hide();
					sync_modules_from_plan_apps(frm, { prune: true });
					frappe.show_alert({ message: __("تم تحديث التطبيقات. احفظ الباقة."), indicator: "green" });
				},
			});
			d.show();
		},
	});
}

function fill_default_modules(frm) {
	const defaults = [
		["Accounts", "المحاسبة"],
		["Selling", "المبيعات"],
		["Buying", "المشتريات"],
		["Stock", "المخزون"],
		["Setup", "الإعداد"],
	];
	frm.clear_table("plan_modules");
	defaults.forEach(([name, label]) => {
		const row = frm.add_child("plan_modules");
		row.module_name = name;
		row.module_label = label;
		row.enabled = 1;
		row.source_app = "erpnext";
	});
	if (!(frm.doc.plan_apps || []).length) {
		const row = frm.add_child("plan_apps");
		row.app_name = "erpnext";
		row.app_label = "ERPNext";
		row.install = 1;
	}
	frm.refresh_fields(["plan_modules", "plan_apps"]);
}

function cint(v) {
	return frappe.utils.cint(v);
}
