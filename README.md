# Superadmin

Frappe application for **central tenant registration** on one management site: create **Tenant Company** records, generate **hosts file** hints for clients, and provision **new Bench sites** via background jobs (`bench new-site`, then `bench install-app …`).

## Compatibility

Designed to be **ERPNext-version agnostic**:

- No Python import of ERPNext (only optional `bench install-app erpnext` when the app exists on the bench).
- Works on **Frappe v14+ / v15 / v16** style desks (DocType + whitelist APIs).
- Docker-aware `bench new-site` flags (`--no-mariadb-socket`, `--mariadb-user-host-login-scope=%`) are added only when helpful and dropped when the local `bench` CLI does not support them.
- MariaDB root password can come from site config **or** common Docker env vars (`DB_PASSWORD`, `MYSQL_ROOT_PASSWORD`, …).

Works best when:

- The **same Bench** hosts both the management site and tenant sites.
- **`bench`**, **`bench worker`** (long queue), and **MariaDB** are available to the process that runs jobs.
- Target apps (default **erpnext** if present) exist under `bench/apps/` before provisioning.

> **Docker single-site note:** Installing this app on a single-site `frappe_docker` stack enables the UI and APIs. Creating additional tenant hostnames still requires multi-site routing (DNS + reverse proxy / `FRAPPE_SITE_NAME_HEADER`) and enough disk.

---

## Requirements

| Requirement | Notes |
|-------------|--------|
| Frappe | v14+ typical; Python **3.10+**. |
| Bench | `bench new-site`, `bench install-app`, `bench --site … set-maintenance-mode`. |
| Redis / RQ | Long worker must run for provisioning jobs. |
| MariaDB root password | Needed for non-interactive `bench new-site`. |
| Multi-site routing | For separate hostnames per tenant, enable DNS multitenant + nginx as in Frappe docs. |

---

## Install (classic Bench)

```bash
cd /path/to/frappe-bench
bench get-app /path/to/superadmin   # or git URL
bench --site your.management.site install-app superadmin
bench migrate
bench build --app superadmin
bench clear-cache
```

## Install (frappe_docker bind-mount)

Mount the app into containers at `/home/frappe/frappe-bench/apps/superadmin`, then:

```bash
bench --site <site> install-app superadmin
bench build --app superadmin
bench clear-cache
```

Ensure **`bench worker`** is running so provisioning jobs leave the **Queued** state.

---

## Configuration

### 1. MariaDB root password (required for provisioning)

Add **one** of:

**`sites/common_site_config.json`**

```json
"superadmin_mariadb_root_password": "YOUR_MARIADB_ROOT_PASSWORD"
```

Or environment variable for the worker process:

```bash
export SUPERADMIN_MARIADB_ROOT_PASSWORD="..."
# Docker aliases also accepted: DB_PASSWORD, MYSQL_ROOT_PASSWORD, MARIADB_ROOT_PASSWORD
```

### 2. Apps installed on each new tenant (optional)

Priority:

1. **Tenant Company → Install apps**
2. **`superadmin_tenant_install_apps`** in site/common config
3. Hook `superadmin_default_install_apps` / auto-detect `erpnext` on bench

---

## SaaS layer (plans, billing, portal)

**English:** The Superadmin app includes a SaaS control plane on the **management site**: **SaaS Plan / Subscription / Invoice / Coupon**, tenant limits pushed into each site’s `site_config.json`, hourly subscription enforcement, daily scheduled backups, guest pages (`/pricing`, `/account`, `/signup?plan=`), and the **SaaS Overview** script report. Platform roles: **Platform Admin**, **Platform Billing**, **Platform Support**, **Platform Ops**. **Multi-server orchestration is deferred** — a single default **Server Node** is seeded for now.

**العربية:** طبقة SaaS على موقع الإدارة: خطط واشتراكات وفواتير وكوبونات، حدود لكل عميل، نسخ احتياطي مجدول، بوابة عملاء وأسعار، وتقرير **SaaS Overview**. تنسيق عدة خوادم **مؤجل** حاليًا.

After pulling these changes:

```bash
bench --site <management-site> migrate
bench build --app superadmin
bench clear-cache
```

Ensure **hourly/daily scheduler** (`bench schedule` or equivalent) runs for `enforce_all_subscriptions` and `enqueue_scheduled_backups`.

Desk: **Superadmin → SaaS Overview** report; API `superadmin.analytics.get_saas_dashboard_metrics` for programmatic metrics.

### Ops flags

| Config key | Purpose |
|------------|---------|
| `superadmin_allow_delete_without_backup` | Allow delete if pre-delete backup fails |
| `superadmin_allow_restore` | Enable restore API (still lab-oriented) |
| `superadmin_restore_lab_site` | Target lab site name for restore hints |

### Public routes

`/`, `/pricing`, `/signup?plan=`, `/verify`, `/portal-login`, `/account`

### Scheduler

- Hourly: `superadmin.limits.enforce_all_subscriptions` (status + max_users)
- Daily: `superadmin.backup.enqueue_scheduled_backups` (+ retention prune)


---

## License

See `license.txt`.
