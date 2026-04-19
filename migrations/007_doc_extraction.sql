-- Phase 3a: Document text extraction

ALTER TABLE messages ADD COLUMN IF NOT EXISTS doc_text TEXT NULL AFTER ocr_text;

-- Recreate FULLTEXT index to include doc_text
SET @ix_exists := (
    SELECT COUNT(*) FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'messages'
      AND INDEX_NAME = 'ft_messages'
);
SET @sql := IF(@ix_exists > 0, 'ALTER TABLE messages DROP INDEX ft_messages', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

ALTER TABLE messages ADD FULLTEXT INDEX ft_messages (text, ocr_text, doc_text);
