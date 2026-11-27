"""Simple Redis-backed rate limiting via frappe.cache."""

from __future__ import annotations

import frappe
from frappe import _


def assert_rate_limit(key: str, limit: int = 8, window_seconds: int = 600) -> None:
	"""Increment a counter for `key` and throw if over `limit` within the window."""
	cache = frappe.cache()
	full_key = f"superadmin:rate_limit:{key}"
	count = cache.get(full_key)
	if count is None:
		cache.setex(full_key, window_seconds, 1)
		return
	count = int(count)
	if count >= limit:
		frappe.throw(
			_("Too many requests. Please try again later."),
			frappe.ValidationError,
			title=_("Rate limit exceeded"),
		)
	cache.incr(full_key)
