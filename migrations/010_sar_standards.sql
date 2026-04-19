-- Phase 5: SAR / Evidence Archive — มาตรฐานการศึกษา + การผูกข้อความกับมาตรฐาน

CREATE TABLE IF NOT EXISTS standards (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    code            VARCHAR(32) NOT NULL,
    title           VARCHAR(255) NOT NULL,
    parent_code     VARCHAR(32) NULL,
    description     TEXT NULL,
    academic_year   VARCHAR(8) NULL,
    is_active       TINYINT NOT NULL DEFAULT 1,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_standards_code (code),
    INDEX ix_standards_parent (parent_code),
    INDEX ix_standards_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS message_standards (
    message_id   BIGINT NOT NULL,
    standard_id  INT NOT NULL,
    confidence   FLOAT NOT NULL DEFAULT 0,
    source       VARCHAR(16) NOT NULL DEFAULT 'auto',
    note         VARCHAR(512) NULL,
    created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (message_id, standard_id),
    INDEX ix_ms_standard (standard_id),
    INDEX ix_ms_source (source),
    CONSTRAINT fk_ms_msg FOREIGN KEY (message_id)  REFERENCES messages(id)  ON DELETE CASCADE,
    CONSTRAINT fk_ms_std FOREIGN KEY (standard_id) REFERENCES standards(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Seed มาตรฐานการศึกษาขั้นพื้นฐาน (สพฐ. 3 มาตรฐานหลัก + ตัวบ่งชี้ย่อย)
INSERT INTO standards (code, title, parent_code, description) VALUES
  ('1',   'คุณภาพของผู้เรียน', NULL, 'ผลสัมฤทธิ์ทางวิชาการและคุณลักษณะที่พึงประสงค์ของผู้เรียน'),
  ('1.1', 'ผลสัมฤทธิ์ทางวิชาการของผู้เรียน', '1', 'ความสามารถในการอ่าน เขียน สื่อสาร คิดคำนวณ คิดวิเคราะห์ ใช้เทคโนโลยี และผลสัมฤทธิ์ตามหลักสูตร'),
  ('1.2', 'คุณลักษณะที่พึงประสงค์ของผู้เรียน', '1', 'คุณธรรม จริยธรรม ค่านิยมที่ดี ความภูมิใจในท้องถิ่นและความเป็นไทย'),
  ('2',   'กระบวนการบริหารและการจัดการ', NULL, 'มีเป้าหมาย วิสัยทัศน์ พันธกิจ และระบบบริหารจัดการคุณภาพของสถานศึกษา'),
  ('2.1', 'เป้าหมาย วิสัยทัศน์ พันธกิจที่สถานศึกษากำหนดชัดเจน', '2', NULL),
  ('2.2', 'มีระบบบริหารจัดการคุณภาพของสถานศึกษา', '2', NULL),
  ('3',   'กระบวนการจัดการเรียนการสอนที่เน้นผู้เรียนเป็นสำคัญ', NULL, 'การจัดการเรียนรู้ที่เน้นผู้เรียนเป็นสำคัญและตรวจสอบผลการเรียนรู้อย่างเป็นระบบ'),
  ('3.1', 'จัดการเรียนรู้ผ่านกระบวนการคิดและปฏิบัติจริง', '3', NULL),
  ('3.2', 'ใช้สื่อ เทคโนโลยีสารสนเทศ และแหล่งเรียนรู้ที่เอื้อต่อการเรียนรู้', '3', NULL)
ON DUPLICATE KEY UPDATE title=VALUES(title), description=VALUES(description);
