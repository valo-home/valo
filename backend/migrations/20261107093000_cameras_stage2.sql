-- Modify "cameras" table
ALTER TABLE "public"."cameras" ADD COLUMN "health" jsonb NOT NULL DEFAULT '{}', ADD COLUMN "presets" jsonb NOT NULL DEFAULT '[]';
-- Modify "media" table
ALTER TABLE "public"."media" ADD COLUMN "keep" boolean NOT NULL DEFAULT false;
