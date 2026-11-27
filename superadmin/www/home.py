no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.show_sidebar = False
	context.add_breadcrumbs = False
	context.no_header = 1
	context.title = "ORACPC — نظام إدارة الأعمال السحابي"
	context.portal = {}
	context.plans = []
	context.show_plans = False
	try:
		from superadmin.portal_api import get_portal_content, get_public_plans

		context.portal = get_portal_content() or {}
		context.show_plans = bool(context.portal.get("show_plans_section"))
		if context.show_plans:
			context.plans = get_public_plans() or []
	except Exception:
		pass
