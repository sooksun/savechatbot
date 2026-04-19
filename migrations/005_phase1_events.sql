-- Phase 1: raw event log, group members, unsend support

CREATE TABLE IF NOT EXISTS webhook_raw_events (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    event_type      VARCHAR(32) NOT NULL,
    source_type     VARCHAR(16),
    line_group_id   VARCHAR(64),
    line_user_id    VARCHAR(64),
    webhook_event_id VARCHAR(64) UNIQUE,
    payload         TEXT NOT NULL,
    received_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX ix_wre_event_type (event_type),
    INDEX ix_wre_group (line_group_id),
    INDEX ix_wre_received (received_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS group_members (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    group_id    BIGINT NOT NULL,
    user_id     BIGINT NOT NULL,
    joined_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    left_at     DATETIME,
    is_active   TINYINT(1) NOT NULL DEFAULT 1,
    UNIQUE KEY uq_group_member (group_id, user_id),
    INDEX ix_gm_group (group_id),
    INDEX ix_gm_user (user_id),
    CONSTRAINT fk_gm_group FOREIGN KEY (group_id) REFERENCES groups(id),
    CONSTRAINT fk_gm_user  FOREIGN KEY (user_id)  REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

ALTER TABLE messages ADD COLUMN IF NOT EXISTS webhook_event_id BIGINT NULL AFTER category_id;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS is_unsent TINYINT(1) NOT NULL DEFAULT 0 AFTER original_filename;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS unsent_at DATETIME NULL AFTER is_unsent;

-- Drop FK if exists, then re-add (MariaDB has no IF NOT EXISTS for constraints)
SET @fk_exists := (
    SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'messages'
      AND CONSTRAINT_NAME = 'fk_msg_raw_event'
);
SET @sql := IF(@fk_exists = 0,
    'ALTER TABLE messages ADD CONSTRAINT fk_msg_raw_event FOREIGN KEY (webhook_event_id) REFERENCES webhook_raw_events(id)',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
