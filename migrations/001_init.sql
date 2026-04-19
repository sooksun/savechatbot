-- Run this once to create the database. Then let SQLAlchemy create tables on startup,
-- or run: python -m app.init_db
CREATE DATABASE IF NOT EXISTS getchatbot
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

-- Seed default hybrid categories (Gemini will still add "auto" categories).
-- Run AFTER tables are created.
INSERT IGNORE INTO categories (name, description, is_auto) VALUES
  ('งานลูกค้า',      'ติดต่อ/คำถาม/ดีล จากลูกค้า',        0),
  ('งานผลิต',        'การผลิตชิ้นงาน กราฟิก วิดีโอ',       0),
  ('การตลาด',        'โฆษณา โปรโมชั่น แคมเปญ',           0),
  ('ประชุม/นัดหมาย',  'นัดประชุม กำหนดการ',                0),
  ('ทรัพยากร/ลิงก์',  'ลิงก์ไฟล์ อ้างอิง Drive/Canva',     0),
  ('อื่นๆ',          'จัดกลุ่มไม่ได้',                      0);
