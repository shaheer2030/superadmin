# Superadmin

Frappe application for **central tenant registration** on one management site: create **Tenant Company** records, generate **hosts file** hints for clients, and provision **new Bench sites** via background jobs (`bench new-site`, then `bench install-app …`).

Works with **any ERPNext / Frappe stack** where:

- The **same Bench** hosts both the management site and tenant sites.
- **`bench`**, **`bench worker`** (long queue), and **MariaDB** are available to the process that runs jobs.
- Target apps (default **erpnext**) exist under `bench/apps/` before provisioning.

There is **no Python import** of ERPNext inside superadmin — only `bench` CLI calls — so ERPNext upgrades affect tenants the same way as a normal manual install.

---

## Requirements

| Requirement | Notes |
|-------------|--------|
| Frappe | v14+ typical; Python **3.8+** (`pyproject.toml`). |
| Bench | `bench new-site`, `bench install-app`, `bench --site … set-maintenance-mode` available. |
| Redis / RQ | Long worker must run for provisioning jobs (`bench worker` or equivalent). |
| MariaDB root password | Needed for non-interactive `bench new-site` (see below). |
| Multi-site routing | For separate hostnames per tenant, enable DNS multitenant + nginx as in Frappe docs. |

---

## Install

```bash
cd /path/to/frappe-bench
bench get-app https://github.com/your-org/superadmin.git   # or copy apps/superadmin
bench pip install -e ./apps/superadmin
bench --site your.management.site install-app superadmin
bench migrate
bench build --app superadmin
bench clear-cache
```

Ensure **`bench worker`** is running so provisioning jobs leave the **Queued** state.

---

## Configuration

### 1. MariaDB root password (required for provisioning)

Add **one** of:

**`sites/common_site_config.json`** (all sites):

```json
"superadmin_mariadb_root_password": "YOUR_MARIADB_ROOT_PASSWORD"
```

Or **`sites/your.management.site/site_config.json`** (management site only).

Or environment variable for the worker process:

```bash
export SUPERADMIN_MARIADB_ROOT_PASSWORD="YOUR_MARIADB_ROOT_PASSWORD"
```

### 2. Apps installed on each new tenant (optional)

Priority:

1. **Tenant Company → Install apps** (comma or newline separated), e.g. `erpnext` or `erpnext\nhrms`.
2. **`sites/common_site_config.json`**:

```json
"superadmin_tenant_install_apps": ["erpnext"]
```

(string with commas also works).

3. Hook in **`hooks.py`** (fork/adjust):

```python
superadmin_default_install_apps = ["erpnext"]
```

Every name must be a **folder under `bench/apps/`** (`bench get-app` / `git clone` before provisioning).

### 3. Suspend / activate tenant

Uses `bench --site <site> set-maintenance-mode on|off`. Runs from **`superadmin.tenant_access`** (not `api`) so workers pick up code without stale module issues.

---

## Operations checklist

1. **Worker**: `bench worker` (or scheduler stack that processes `long` queue).
2. **Restart** after pulling code updates: `bench restart` (or reload Gunicorn).
3. **Assets**: `bench build --app superadmin` after changing `public/js`.
4. **Secrets**: Do not commit `common_site_config.json` with passwords; use env or server-only config.

---

## Windows client hosts file

After the site is **Active**, use **Hosts File Entry** on client PCs, e.g.:

`C:\Windows\System32\drivers\etc\hosts`

```
203.0.113.10   company1.local
```

---

## Troubleshooting

| Symptom | What to check |
|--------|----------------|
| Job stuck **Queued** / empty log | `bench worker`, Redis, long queue. |
| **module has no attribute** on API | `bench clear-cache` + `bench restart`; use `superadmin.tenant_access.*` for suspend/activate. |
| **install-app** fails | App missing under `bench/apps`, wrong ERPNext branch, or DB permissions. |
| **new-site** fails | MariaDB root password, hostname already used, disk space. |

---

## License

See `license.txt`.
