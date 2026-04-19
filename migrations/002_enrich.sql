-- Run this once on existing databases to add new columns.
ALTER TABLE messages ADD COLUMN ocr_text TEXT NULL AFTER text;
