(() => {
	function brandingLogo() {
		return (
			(frappe.boot && frappe.boot.app_logo_url) ||
			(frappe.boot &&
				frappe.boot.navbar_settings &&
				frappe.boot.navbar_settings.app_logo) ||
			null
		);
	}

	function patchAppsDataLogo() {
		const logo = brandingLogo();
		if (!logo || !frappe.boot || !frappe.boot.apps_data || !frappe.boot.apps_data.apps) {
			return logo;
		}
		frappe.boot.apps_data.apps.forEach((app) => {
			if (!app) return;
			if (app.logo) app.logo = logo;
			if (app.app_logo_url) app.app_logo_url = logo;
		});
		return logo;
	}

	function patchIntroApps() {
		const logo = patchAppsDataLogo();
		if (!logo || !frappe.setup || !Array.isArray(frappe.setup.intro_apps)) {
			return logo;
		}
		frappe.setup.intro_apps.forEach((app) => {
			if (app && app.logo) {
				app.logo = logo;
			}
		});
		return logo;
	}

	function patchSetupWizardIntro() {
		if (!frappe.setup || !frappe.setup.on) {
			return;
		}
		frappe.setup.on("before_load", () => {
			// intro_apps is already filtered from apps_data; rewrite logos before make_intro
			patchIntroApps();
		});
		frappe.setup.on("after_load", () => {
			const logo = brandingLogo();
			if (!logo) return;
			document.querySelectorAll(".setup-intro__logo").forEach((img) => {
				img.setAttribute("src", logo);
			});
		});
	}

	function watchSetupIntroLogos() {
		const logo = brandingLogo();
		if (!logo || !document.body) return;
		const apply = () => {
			document.querySelectorAll(".setup-intro__logo").forEach((img) => {
				if (img.getAttribute("src") !== logo) {
					img.setAttribute("src", logo);
				}
			});
		};
		apply();
		const observer = new MutationObserver(apply);
		observer.observe(document.body, { childList: true, subtree: true });
		setTimeout(() => observer.disconnect(), 60000);
	}

	function patchSidebarLogoSoon() {
		const logo = brandingLogo();
		if (!logo) return;
		const apply = () => {
			document
				.querySelectorAll(
					'.sidebar-header img, .app-logo img, img[src*="erpnext-logo"], img[src*="frappe-favicon"]'
				)
				.forEach((img) => {
					if (img && img.getAttribute("src") !== logo) {
						img.setAttribute("src", logo);
					}
				});
		};
		apply();
		setTimeout(apply, 500);
		setTimeout(apply, 1500);
	}

	function boot() {
		patchAppsDataLogo();
		patchSetupWizardIntro();
		patchSidebarLogoSoon();
		watchSetupIntroLogos();
	}

	if (window.frappe) {
		if (frappe.ready) {
			frappe.ready(boot);
		} else {
			document.addEventListener("DOMContentLoaded", boot);
		}
		// Register early in case setup page loads before frappe.ready
		patchAppsDataLogo();
		patchSetupWizardIntro();
	}
})();
