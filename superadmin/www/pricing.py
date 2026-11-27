no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.show_sidebar = False
	context.add_breadcrumbs = False
	context.no_header = 1
	context.title = "الأسعار — ORACPC"
	context.plans = []
	context.portal = {}
	try:
		from superadmin.portal_api import get_portal_content, get_public_plans

		context.plans = get_public_plans() or []
		context.portal = get_portal_content() or {}
	except Exception:
		pass