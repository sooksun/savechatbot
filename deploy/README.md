# Deploy: savechatbot on Ubuntu (Docker)

Target: `/DATA/AppData/www/savechatbot` on Ubuntu, sharing the existing
MariaDB container (`linuxserver/mariadb:11.4.8`, container id `93071d348e3b`,
named `mariadb`, publishing host port `3306`).

## 1) ก๊อปโค้ดขึ้นเครื่อง

```bash
sudo mkdir -p /DATA/AppData/www/savechatbot
sudo chown -R "$USER":"$USER" /DATA/AppData/www/savechatbot
cd /DATA/AppData/www/savechatbot

# วิธีที่ 1: clone
git clone <repo-url> .

# วิธีที่ 2: rsync จากเครื่อง dev
# rsync -avz --exclude .venv --exclude storage ./getchatbot/ user@server:/DATA/AppData/www/savechatbot/
```

## 2) เตรียม .env

```bash
cp .env.production.example .env
nano .env   # ใส่ LINE_*, GEMINI_API_KEY, APP_BASE_URL, DASHBOARD_PASSWORD
```

DB ตั้งค่าไว้แล้ว:
```
DB_HOST=host.docker.internal
DB_USER=root
DB_PASSWORD=l6-lyo9N
DB_NAME=savechatbot
```
`host.docker.internal` ถูก map ไปที่ host gateway ใน `docker-compose.prod.yml`
จึงไปถึง MariaDB ที่ publish port 3306 บน host ได้โดยตรง โดยไม่ต้องแก้ network เดิม

## 3) สร้าง DB + ตาราง

```bash
chmod +x deploy/*.sh
./deploy/bootstrap_db.sh
```

สคริปต์จะ:
1. `CREATE DATABASE savechatbot` (ถ้ายังไม่มี) ใน container `mariadb`
2. รัน `python -m app.init_db` สร้างตารางผ่าน SQLAlchemy
3. seed หมวดหมู่เริ่มต้นจาก `migrations/001_init.sql`
4. ปรับสคีมาเพิ่ม column `ocr_text` จาก `migrations/002_enrich.sql`

> ถ้าชื่อ container MariaDB ของคุณไม่ใช่ `mariadb` ให้ override:
> `MARIADB_CONTAINER=<ชื่อจริง> ./deploy/bootstrap_db.sh`

## 4) Build + รัน

```bash
./deploy/deploy.sh
```

ตรวจสอบ:
```bash
curl http://127.0.0.1:8000/health
docker compose -f docker-compose.prod.yml logs -f app
```

## 5) Reverse proxy + HTTPS (Nginx + Let's Encrypt)

```bash
sudo cp deploy/nginx.savechatbot.conf /etc/nginx/sites-available/savechatbot.conf
sudo sed -i 's/savechatbot.example.com/your-domain.com/g' /etc/nginx/sites-available/savechatbot.conf
sudo ln -sf /etc/nginx/sites-available/savechatbot.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

จากนั้นใน LINE Developers Console → Messaging API channel → Webhook URL =
`https://your-domain.com/webhook` แล้วกด **Verify**

## 6) Update โค้ดใหม่

```bash
cd /DATA/AppData/www/savechatbot
git pull
./deploy/deploy.sh           # build + restart
```

ถ้ามี migration ใหม่:
```bash
docker exec -i mariadb mariadb -uroot -p'l6-lyo9N' savechatbot < migrations/00X_xxx.sql
```

## 7) คำสั่งดูแลที่ใช้บ่อย

```bash
# รีสตาร์ทอย่างเดียว
docker compose -f docker-compose.prod.yml restart app

# หยุด
docker compose -f docker-compose.prod.yml down

# เข้า shell ใน container
docker exec -it savechatbot bash

# สร้างสรุปย้อนหลังจาก CLI
docker exec savechatbot python -c \
  "from app.services.summarizer import generate_summary; \
   from datetime import date, timedelta; \
   generate_summary('daily', date.today()-timedelta(days=1))"

# ตรวจการเชื่อมต่อ DB จากใน container
docker exec savechatbot python -c \
  "from app.database import engine; \
   print(engine.connect().execute(__import__('sqlalchemy').text('select 1')).scalar())"
```

## Troubleshooting

- **`Can't connect to MySQL server on 'host.docker.internal'`**
  ตรวจว่า MariaDB publish port 3306 ที่ host จริง: `docker port mariadb`
  ต้องเห็น `3306/tcp -> 0.0.0.0:3306`
- **Permission denied บน storage/**
  `sudo chown -R 1000:1000 /DATA/AppData/www/savechatbot/storage`
- **Webhook signature fail**
  เช็คว่า `LINE_CHANNEL_SECRET` ตรงกับใน LINE Developers Console
- **Cron job ไม่ทำงาน**
  ตั้งเวลาให้ `TIMEZONE=Asia/Bangkok` แล้วรีสตาร์ท container
