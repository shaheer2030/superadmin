# Superadmin

تطبيق لوحة تحكم مركزية على موقع إداري واحد (مثل `site1.local`) لتسجيل شركات المستأجرين وتوليد سطر **ملف hosts** لكل عميل وإطلاق إنشاء موقع Bench عبر مهمة خلفية.

## إعداد كلمة مرور جذر MariaDB للتوفير التلقائي

أضف في `sites/common_site_config.json` أو في `sites/site1.local/site_config.json`:

```json
"superadmin_mariadb_root_password": "YOUR_ROOT_PASSWORD"
```

أو عرّف متغير البيئة `SUPERADMIN_MARIADB_ROOT_PASSWORD` لعملية الـ worker التي تنفّذ المهام الطويلة.

## تثبيت التطبيق

```bash
cd /path/to/frappe-bench
bench pip install -e ./apps/superadmin
bench --site site1.local install-app superadmin
bench migrate
bench clear-cache
```

## سطر ملف hosts (ويندوز)

بعد إنشاء الموقع، انسخ الحقل **Hosts File Entry** من سجل Tenant Company وأضفه إلى:

`C:\Windows\System32\drivers\etc\hosts`

مثال:

```
192.168.124.137 company1.local
```
