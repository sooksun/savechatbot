-- Sprint 4: retry queue for background enrichment.
ALTER TABLE messages
  ADD COLUMN enrich_status VARCHAR(16) NOT NULL DEFAULT 'pending',
  ADD COLUMN enrich_attempts INT NOT NULL DEFAULT 0,
  ADD COLUMN enrich_error VARCHAR(512) NULL,
  ADD INDEX ix_messages_enrich_status (enrich_status);

-- Backfill: historical rows are already processed, mark them done.
UPDATE messages SET enrich_status = 'done' WHERE enrich_status = 'pending';
