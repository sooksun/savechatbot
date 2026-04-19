-- Phase 3b: YouTube transcript + summary per link

ALTER TABLE links ADD COLUMN IF NOT EXISTS transcript TEXT NULL AFTER title;
ALTER TABLE links ADD COLUMN IF NOT EXISTS summary    TEXT NULL AFTER transcript;
