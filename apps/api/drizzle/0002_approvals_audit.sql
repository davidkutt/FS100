CREATE TABLE "approvals" (
	"id" uuid PRIMARY KEY NOT NULL,
	"conversation_id" uuid NOT NULL,
	"message_id" uuid NOT NULL,
	"requester_id" text NOT NULL,
	"call_id" text NOT NULL,
	"tool" text NOT NULL,
	"args" jsonb NOT NULL,
	"risk" text NOT NULL,
	"signed_action" text NOT NULL,
	"status" text DEFAULT 'pending' NOT NULL,
	"note" text,
	"error" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"expires_at" timestamp with time zone NOT NULL,
	"decided_at" timestamp with time zone,
	"executed_at" timestamp with time zone,
	CONSTRAINT "approvals_status_check" CHECK ("approvals"."status" in ('pending','approved','rejected','expired','executing','succeeded','failed','unknown'))
);
--> statement-breakpoint
CREATE TABLE "audit_log" (
	"id" bigserial PRIMARY KEY NOT NULL,
	"ts" timestamp with time zone DEFAULT now() NOT NULL,
	"actor_id" text NOT NULL,
	"actor_roles" text[] NOT NULL,
	"service_identity" text,
	"conversation_id" uuid,
	"approval_id" uuid,
	"tool" text NOT NULL,
	"kind" text NOT NULL,
	"args_redacted" jsonb,
	"outcome" text NOT NULL,
	"trace_id" text
);
--> statement-breakpoint
ALTER TABLE "approvals" ADD CONSTRAINT "approvals_conversation_id_conversations_id_fk" FOREIGN KEY ("conversation_id") REFERENCES "public"."conversations"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "approvals" ADD CONSTRAINT "approvals_message_id_messages_id_fk" FOREIGN KEY ("message_id") REFERENCES "public"."messages"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "approvals_requester_id_status_index" ON "approvals" USING btree ("requester_id","status");--> statement-breakpoint
CREATE INDEX "approvals_conversation_id_index" ON "approvals" USING btree ("conversation_id");--> statement-breakpoint
CREATE INDEX "audit_log_ts_index" ON "audit_log" USING btree ("ts");--> statement-breakpoint
CREATE INDEX "audit_log_actor_id_ts_index" ON "audit_log" USING btree ("actor_id","ts");--> statement-breakpoint
-- Hand-written (drizzle-kit has no triggers): the app role may only insert and read audit rows (D42).
CREATE FUNCTION "audit_log_append_only"() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
	RAISE EXCEPTION 'audit_log is append-only';
END;
$$;--> statement-breakpoint
CREATE TRIGGER "audit_log_append_only" BEFORE UPDATE OR DELETE OR TRUNCATE ON "audit_log" FOR EACH STATEMENT EXECUTE FUNCTION "audit_log_append_only"();
