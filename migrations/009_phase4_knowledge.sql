-- Phase 4: entities, decisions, action items

CREATE TABLE IF NOT EXISTS entities (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    kind            VARCHAR(32) NOT NULL,
    name            VARCHAR(255) NOT NULL,
    normalized      VARCHAR(255) NOT NULL,
    mention_count   INT NOT NULL DEFAULT 1,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_entity_kind_name (kind, normalized),
    INDEX ix_entities_kind (kind),
    INDEX ix_entities_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS entity_mentions (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    entity_id   INT NOT NULL,
    message_id  BIGINT NOT NULL,
    UNIQUE KEY uq_em (entity_id, message_id),
    INDEX ix_em_entity (entity_id),
    INDEX ix_em_msg (message_id),
    CONSTRAINT fk_em_entity  FOREIGN KEY (entity_id)  REFERENCES entities(id) ON DELETE CASCADE,
    CONSTRAINT fk_em_message FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS decisions (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    message_id  BIGINT NOT NULL,
    group_id    BIGINT,
    summary     VARCHAR(512) NOT NULL,
    decided_at  DATETIME NOT NULL,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX ix_dec_group (group_id),
    INDEX ix_dec_msg (message_id),
    INDEX ix_dec_decided (decided_at),
    CONSTRAINT fk_dec_msg   FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
    CONSTRAINT fk_dec_group FOREIGN KEY (group_id)   REFERENCES groups(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS action_items (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    message_id  BIGINT NOT NULL,
    group_id    BIGINT,
    task        VARCHAR(512) NOT NULL,
    assignee    VARCHAR(128),
    due_date    DATE,
    status      VARCHAR(16) NOT NULL DEFAULT 'open',
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX ix_ai_group (group_id),
    INDEX ix_ai_msg (message_id),
    INDEX ix_ai_due (due_date),
    CONSTRAINT fk_ai_msg   FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
    CONSTRAINT fk_ai_group FOREIGN KEY (group_id)   REFERENCES groups(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
