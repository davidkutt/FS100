ALTER TABLE "documents" DROP CONSTRAINT "documents_status_check";--> statement-breakpoint
-- Hand-written: an ingest that ran in the old API process cannot resume.
UPDATE "documents" SET "status" = 'failed', "error" = 'Interrupted by an API restart; delete and upload again' WHERE "status" = 'processing';--> statement-breakpoint
ALTER TABLE "documents" ADD COLUMN "version" integer DEFAULT 1 NOT NULL;--> statement-breakpoint
ALTER TABLE "documents" ADD COLUMN "job_id" text;--> statement-breakpoint
ALTER TABLE "documents" ADD CONSTRAINT "documents_status_check" CHECK ("documents"."status" in ('pending','queued','parsing','embedding','ready','failed'));