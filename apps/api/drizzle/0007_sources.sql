ALTER TABLE "documents" ADD COLUMN "source" text;--> statement-breakpoint
ALTER TABLE "documents" ADD CONSTRAINT "documents_source_unique" UNIQUE("source");