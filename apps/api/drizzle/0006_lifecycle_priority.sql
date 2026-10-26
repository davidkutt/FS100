ALTER TABLE "documents" ADD COLUMN "lifecycle" text DEFAULT 'active' NOT NULL;--> statement-breakpoint
ALTER TABLE "documents" ADD COLUMN "priority" text DEFAULT 'normal' NOT NULL;--> statement-breakpoint
ALTER TABLE "documents" ADD COLUMN "priority_topics" text[] DEFAULT '{}' NOT NULL;--> statement-breakpoint
ALTER TABLE "documents" ADD CONSTRAINT "documents_lifecycle_check" CHECK ("documents"."lifecycle" in ('active','retired'));--> statement-breakpoint
ALTER TABLE "documents" ADD CONSTRAINT "documents_priority_check" CHECK ("documents"."priority" in ('canonical','normal','low'));