CREATE TABLE "documents" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"owner_id" text NOT NULL,
	"owner_name" text NOT NULL,
	"filename" text NOT NULL,
	"mime" text NOT NULL,
	"size_bytes" integer NOT NULL,
	"sha256" char(64) NOT NULL,
	"domains" text[] DEFAULT '{}' NOT NULL,
	"status" text NOT NULL,
	"error" text,
	"chunk_count" integer,
	"page_count" integer,
	"embedding_model" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "documents_sha256_unique" UNIQUE("sha256"),
	CONSTRAINT "documents_status_check" CHECK ("documents"."status" in ('pending','processing','ready','failed'))
);
