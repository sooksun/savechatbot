# GetChatBot

LINE Messaging bot ที่บันทึกข้อความ / รูปภาพ / ลิงก์ (YouTube, Google Drive, Canva) จากกลุ่ม LINE
แล้วจัดหมวดหมู่ด้วย Gemini API และสรุปเป็น **รายวัน / รายสัปดาห์** ให้ดูผ่าน Web Dashboard

## Stack
- Python 3.12 + FastAPI
- MySQL 8 (SQLAlchemy 2)
- Gemini API (`google-genai`) — จัดหมวด + สรุป
- APScheduler — ยิง job รายวัน/รายสัปดาห์
- Jinja2 templates — หน้า dashboard

## โครงสร้าง

```
app/
  main.py                  # FastAPI entry, mount webhook + dashboard + /media
  config.py                # pydantic-settings อ่าน .env
  database.py              # SQLAlchemy engine / session
  models.py                # Group / User / Message / Link / Category / Summary
  webhook.py               # /webhook รับ event จาก LINE
  scheduler.py             # daily + weekly jobs
  services/
    line_client.py         # profile / group summary
    media_storage.py       # ดาวน์โหลดรูป/ไฟล์จาก LINE Content API
    link_extractor.py      # แยก youtube / google_drive / canva / other
    gemini_client.py       # classify_message + summarize_conversations
    summarizer.py          # สร้างสรุปและบันทึก
  dashboard/
    routes.py              # / , /messages , /links , /summaries , /categories
    auth.py                # HTTP Basic
    templates/             # base, index, messages, links, summaries, categories
migrations/001_init.sql    # สร้าง DB + seed หมวดเริ่มต้น
storage/media/             # ไฟล์รูปที่ดาวน์โหลด
```

## Quick start (local)

1. สร้าง DB
   ```sql
   mysql -u root -p < migrations/001_init.sql
   ```
2. เตรียม env
   ```bash
   cp .env.example .env
   # ใส่ LINE_CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN, GEMINI_API_KEY, DB_*
   ```
3. ติดตั้งและสร้างตาราง
   ```bash
   python -m venv .venv && source .venv/bin/activate   # หรือ .venv\Scripts\activate บน Windows
   pip install -r requirements.txt
   python -m app.init_db
   # optional: seed categories
   mysql -u root -p getchatbot < migrations/001_init.sql
   ```
4. รัน
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```
5. เปิด dashboard: http://localhost:8000/ (ล็อกอินด้วย `DASHBOARD_USER` / `DASHBOARD_PASSWORD`)

## ตั้งค่า LINE

1. สร้าง **Messaging API channel** ที่ [LINE Developers Console](https://developers.line.biz/console/)
2. ใน Channel settings:
   - เปิด **Use webhook**
   - ตั้ง **Webhook URL** = `https://<your-domain>/webhook`
   - ปิด **Auto-reply** และ **Greeting message**
3. เพิ่มบอทเป็นสมาชิกของกลุ่ม LINE ที่ต้องการเก็บข้อความ
4. LINE เก็บ media content แค่ ~14 วัน — ระบบจะโหลดมาเก็บทันทีที่รับ event

## Deploy (VPS + Docker)

```bash
# บน VPS
git clone <repo> && cd getchatbot
cp .env.example .env   # แก้ค่าจริง รวมถึง APP_BASE_URL และ DB_PASSWORD ที่แข็งแรง
docker compose up -d --build
```

ตั้ง reverse proxy (Nginx / Caddy) + SSL ชี้ `https://your-domain` → `http://127.0.0.1:8000`
ตัวอย่าง Caddyfile:
```
your-domain.com {
  reverse_proxy 127.0.0.1:8000
}
```

## การทำงานของหมวดหมู่ (Hybrid)

- หมวดเริ่มต้นกำหนดไว้ใน `migrations/001_init.sql` (งานลูกค้า, งานผลิต, การตลาด ฯลฯ)
- ทุกข้อความที่เป็น text จะถูกส่งให้ Gemini เลือกหมวด
- ถ้าไม่มีหมวดที่เหมาะ Gemini จะเสนอชื่อใหม่ ระบบจะสร้างหมวด `is_auto=1` ให้อัตโนมัติ
- Admin จัดการหมวดได้ที่ `/categories`

## สรุปอัตโนมัติ

- รายวัน: ทุกวันเวลา `DAILY_SUMMARY_AT` (default 22:00)
- รายสัปดาห์: ทุก `WEEKLY_SUMMARY_DOW` เวลา `WEEKLY_SUMMARY_AT` (default จันทร์ 09:00)
- สรุปแยกต่อกลุ่ม เก็บในตาราง `summaries` ดูได้ที่ `/summaries`
- กดปุ่ม "สร้างสรุป" ในหน้า `/summaries` เพื่อสร้างย้อนหลังได้

## Enrichment (ทำอัตโนมัติหลังรับ event)

- **OCR รูปภาพ** — ใช้ Gemini Vision, บันทึกไว้ที่ `messages.ocr_text`
- **ดึง Title ของลิงก์** — YouTube ใช้ oEmbed, Drive/Canva/อื่นๆ ดึงจาก `<meta og:title>` หรือ `<title>` บันทึกที่ `links.title`
- ทำใน `BackgroundTasks` หลังจากตอบ `200` ให้ LINE — webhook จึงไม่ timeout

## คำสั่งในกลุ่ม LINE

พิมพ์ในห้องแชท (บอทต้องอยู่ในกลุ่ม):

| คำสั่ง | ผลลัพธ์ |
|---|---|
| `!สรุปวันนี้` | สร้าง+ส่งสรุปรายวันของกลุ่ม |
| `!สรุปเมื่อวาน` | สรุปของเมื่อวาน |
| `!สรุปสัปดาห์` | สรุปรายสัปดาห์ |
| `!ถาม <คำถาม>` | ถาม AI จาก RAG ของความรู้ในกลุ่ม |
| `!มฐ` | แสดงรายการมาตรฐาน SAR ทั้งหมด |
| `!แท็ก <รหัส> [หมายเหตุ]` | ผูกข้อความก่อนหน้าเข้ากับมาตรฐาน เช่น `!แท็ก 1.1 งานวันวิทย์` |
| `!help` | แสดงรายการคำสั่ง |

## SAR / Evidence Archive (Phase 5)

ระบบช่วยรวบรวมหลักฐานสำหรับรายงานการประเมินตนเองของสถานศึกษา (SAR) แบบอัตโนมัติ

- ตาราง `standards` เก็บมาตรฐานการศึกษาขั้นพื้นฐาน (สพฐ. 3 มฐ. + ตัวบ่งชี้ย่อย) — admin เพิ่ม/แก้ได้ที่ `/standards`
- ทุก message ที่มีข้อความ (text / ocr_text / doc_text) จะถูก Gemini จัดเข้ามาตรฐาน (สูงสุด 3 รหัส, confidence ≥ 0.4) แบบ background
- ครูผูกเพิ่มเองผ่าน LINE: `!แท็ก 1.1 คำอธิบาย` (ผูกข้อความล่าสุดในกลุ่ม)
- Dashboard:
  - `/standards` — ดูรายการมาตรฐาน + จำนวนหลักฐาน
  - `/standards/{code}` — รายละเอียดหลักฐาน (รูป thumbnail, ไฟล์, ลิงก์, แหล่ง auto/manual)
  - `/standards/{code}/export.pdf` — PDF เฉพาะมาตรฐาน
  - `/sar/export.pdf?year=2568` — เล่มรวม SAR (admin) พร้อมปก/สารบัญ/เลขหน้า

Migration:
```bash
mysql -u root -p getchatbot < migrations/010_sar_standards.sql
```

## Migration สำหรับฐานข้อมูลเดิม

ถ้าเคยสร้างตารางไว้ก่อน ให้รัน:
```bash
mysql -u root -p getchatbot < migrations/002_enrich.sql
```

## สิ่งที่ควรต่อยอด
- Rate limiting ต่อ user, cleanup media เก่า
- Multi-tenant / หลาย channel
- Drive API สำหรับดึง title ของไฟล์ที่ต้อง login

## License
Private use.
