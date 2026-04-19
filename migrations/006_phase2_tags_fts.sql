-- Phase 2: tagging + full-text search

CREATE TABLE IF NOT EXISTS tags (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(64) NOT NULL UNIQUE,
    color       VARCHAR(16) NOT NULL DEFAULT '#6366f1',
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS message_tags (
    message_id  BIGINT NOT NULL,
    tag_id      INT NOT NULL,
    PRIMARY KEY (message_id, tag_id),
    INDEX ix_mt_tag (tag_id),
    CONSTRAINT fk_mt_msg FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
    CONSTRAINT fk_mt_tag FOREIGN KEY (tag_id)     REFERENCES tags(id)     ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Full-text index on text + ocr_text (needs MariaDB 10.0.5+, InnoDB)
SET @ix_exists := (
    SELECT COUNT(*) FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'messages'
      AND INDEX_NAME = 'ft_messages'
);
SET @sql := IF(@ix_exists = 0,
    'ALTER TABLE messages ADD FULLTEXT INDEX ft_messages (text, ocr_text)',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
