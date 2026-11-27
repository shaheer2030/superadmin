// Copyright (c) 2026, Superadmin and contributors
// Hide SaaS-controlled parts of the Setup Wizard persona slides (ERPNext + HRMS):
// industry + module checkboxes. Modules are controlled by the SaaS Plan.
//
// Loaded via site_config app_include_js (before frappe.setup may exist).

(function () {
	"use strict";

	const HIDDEN_EXACT = {
		persona_industry: 1,
		module_accounting: 1,
		module_stock: 1,
		module_manufacturing: 1,
		module_projects: 1,
		module_leave_attendance: 1,
		module_payroll: 1,
		module_recruitment: 1,
		module_performance: 1,
	};

	let hooks_ready = false;
	let page_wrapped = false;
	let observer = null;

	function inject_css() {
		if (document.getElementById("sa-setup-wizard-saas-css")) {
			return;
		}
		const style = document.createElement("style");
		style.id = "sa-setup-wizard-saas-css";
		const parts = Object.keys(HIDDEN_EXACT).map(
			(n) =>
				`.frappe-control[data-fieldname="${n}"], [data-fieldname="${n}"] { display: none !important; }`
		);
		style.textContent = parts.join("\n");
		(document.head || document.documentElement).appendChild(style);
	}

	function should_hide_field(f) {
		if (!f) {
			return false;
		}
		if (f.fieldname && HIDDEN_EXACT[f.fieldname]) {
			return true;
		}
		if (f.fieldname && String(f.fieldname).indexOf("module_") === 0) {
			return true;
		}
		if (f.fieldtype === "Section Break" && f.description) {
			const d = String(f.description).toLowerCase();
			if (d.indexOf("module") !== -1 || d.indexOf("وحدات") !== -1) {
				return true;
			}
		}
		if (f.fieldtype === "Column Break") {
			return true;
		}
		return false;
	}

	function patch_slide(slide) {
		if (!slide) {
			return;
		}
		if (slide.name !== "persona" && slide.name !== "hr_persona") {
			return;
		}
		slide.fields = (slide.fields || []).filter((f) => !should_hide_field(f));
		slide.onload = function () {};
		slide.bind_industry_modules = function () {};
		slide.apply_industry_modules = function () {};
		slide.bind_company_size_modules = function () {};
		slide.apply_company_size_modules = function () {};
	}

	function patch_all_slide_sources() {
		if (window.erpnext && erpnext.setup && Array.isArray(erpnext.setup.slides_settings)) {
			erpnext.setup.slides_settings.forEach(patch_slide);
		}
		if (window.hrms && hrms.setup && Array.isArray(hrms.setup.slides_settings)) {
			hrms.setup.slides_settings.forEach(patch_slide);
		}
		if (frappe.setup && Array.isArray(frappe.setup.slides)) {
			frappe.setup.slides.forEach(patch_slide);
		}
		if (frappe.setup && Array.isArray(frappe.setup.slides_settings)) {
			frappe.setup.slides_settings.forEach(patch_slide);
		}
	}

	function hide_in_dom() {
		Object.keys(HIDDEN_EXACT).forEach((name) => {
			document.querySelectorAll(`[data-fieldname="${name}"]`).forEach((el) => {
				const wrap = el.closest(".frappe-control") || el;
				wrap.style.display = "none";
			});
		});
		document.querySelectorAll(".form-section").forEach((section) => {
			const text = (section.textContent || "").toLowerCase();
			if (
				text.indexOf("select the modules that you plan to implement") !== -1 ||
				text.indexOf("modules that you plan") !== -1
			) {
				section.style.display = "none";
			}
		});
	}

	function watch_dom() {
		if (observer || !document.body) {
			return;
		}
		observer = new MutationObserver(() => hide_in_dom());
		observer.observe(document.body, { childList: true, subtree: true });
		hide_in_dom();
	}

	function wrap_wizard_show() {
		if (!(frappe.wizard && frappe.wizard.show_slide) || frappe.wizard.__sa_hide_patched) {
			return;
		}
		const orig = frappe.wizard.show_slide.bind(frappe.wizard);
		frappe.wizard.show_slide = function () {
			const ret = orig.apply(this, arguments);
			setTimeout(hide_in_dom, 0);
			setTimeout(hide_in_dom, 50);
			setTimeout(hide_in_dom, 250);
			return ret;
		};
		frappe.wizard.__sa_hide_patched = true;
	}

	function on_before_load() {
		patch_all_slide_sources();
	}

	function on_after_load() {
		patch_all_slide_sources();
		wrap_wizard_show();
		watch_dom();
		setTimeout(hide_in_dom, 0);
		setTimeout(hide_in_dom, 100);
		setTimeout(hide_in_dom, 400);
	}

	function install_setup_hooks() {
		if (hooks_ready) {
			return true;
		}
		if (!(window.frappe && frappe.setup && typeof frappe.setup.on === "function")) {
			return false;
		}
		hooks_ready = true;
		frappe.setup.on("before_load", on_before_load);
		frappe.setup.on("after_load", on_after_load);
		return true;
	}

	function wrap_setup_wizard_page() {
		if (page_wrapped) {
			return Boolean(frappe.pages && frappe.pages["setup-wizard"]);
		}
		if (!(frappe.pages && frappe.pages["setup-wizard"])) {
			return false;
		}
		page_wrapped = true;
		const page = frappe.pages["setup-wizard"];
		const orig_load = page.on_page_load;
		page.on_page_load = function (wrapper) {
			install_setup_hooks();
			inject_css();
			const ret = orig_load ? orig_load.apply(this, arguments) : undefined;
			// erpnext overwrites on_page_load when its file loads inside require —
			// re-wrap after a tick if needed, and patch sources once requires finish.
			setTimeout(function () {
				install_setup_hooks();
				patch_all_slide_sources();
				wrap_wizard_show();
				hide_in_dom();
			}, 0);
			return ret;
		};
		const orig_show = page.on_page_show;
		page.on_page_show = function () {
			const ret = orig_show ? orig_show.apply(this, arguments) : undefined;
			setTimeout(hide_in_dom, 0);
			setTimeout(hide_in_dom, 100);
			return ret;
		};
		return true;
	}

	function tick() {
		inject_css();
		install_setup_hooks();
		wrap_setup_wizard_page();
		if (frappe && frappe.wizard) {
			wrap_wizard_show();
		}
		hide_in_dom();
		watch_dom();
	}

	inject_css();
	let n = 0;
	const timer = setInterval(function () {
		n += 1;
		tick();
		if (n > 300) {
			clearInterval(timer);
		}
	}, 50);

	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", tick);
	} else {
		tick();
	}
})();
