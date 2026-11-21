# Superadmin on this Oracle ERPNext Docker stack

- App path (host): `/opt/erpnext-apps/superadmin` (bind-mounted into containers)
- Site: `oracpc.tech`
- Version installed: `0.2.0` (improved local copy; upstream was 0.1.0)
- Compose override: `/home/ubuntu/gitops/compose.custom-apps.yaml`
- After container recreate, run: `/home/ubuntu/gitops/scripts/ensure-superadmin-assets.sh`

## Improvements vs upstream
- `compat.py` for Frappe/ERPNext/Docker version differences
- Soft ERPNext dependency (no required_apps)
- Docker-friendly `bench new-site` flags with CLI capability probing
- Accepts DB password from Docker env aliases
- Safer cross-site `frappe.init` handling

## Important limitation
Creating additional tenant sites still needs multi-site routing (DNS + reverse proxy) and disk headroom.
The Desk UI (Tenant Company) works on the current single-site deployment.

## Multi-tenant subdomains (2026-11-21)

- DNS: Hostinger wildcard `*.oracpc.tech` → A → server IP
- Frappe: `dns_multitenant=1`, frontend `FRAPPE_SITE_NAME_HEADER=$host`
- Host nginx: `server_name oracpc.tech *.oracpc.tech`
- SSL: after Superadmin creates `name.oracpc.tech`, a `.req` is dropped in `apps/superadmin/ssl-queue/`;
  host cron `/home/ubuntu/gitops/scripts/process-ssl-queue.sh` runs certbot + nginx tenant vhost.

In Tenant Company use Site Name like `alnoor.oracpc.tech` (not `.local`).
