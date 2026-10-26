# plan-phase-5.md — Phase 5: Azure

> **Parked 2026-10-26** — see [plan-daily-use.md](plan-daily-use.md).

> **Project (working title):** `kb-agent` — an assistant for the **"Dev of the future"**.
> **Document scope:** Phase 5 of 6 · **Status:** Draft v1 · **Updated:** 2026-10-24 · builds on `plan.md` v2,
> `plan-phase-2.md` v1.1, `plan-phase-3.md` v1, `plan-phase-4.md` v1 and `roadmap-phases-3-6.md` v1.4
> **Estimated effort:** ~55 h core (range 45–72 h) + ~22 h option · ~6 weeks at 8–10 h/week + 1 buffer week
> **Start:** after Phase 4 (expected late August 2027) → public demo URL live ~late September 2027 → target end
> mid/late October 2027
> **Defaults taken for this plan (confirm at M5.0, D107):** public demo = shared **guest account + invite-only reviewer
> accounts**, no self-registration · an **own domain** (fallback: Azure default hostnames) · **workflow integration stays
> an option**

### Review outcome (changes vs. `roadmap-phases-3-6.md` §6)

| Change | Reason |
|---|---|
| **Kick-off M5.0 (3 h), data tier M5.3 (6 h) and ops review M5.9 (2 h)** as own milestones | Quotas take days, and seven facts below need a spike; the data tier and the cost check were hidden inside other milestones. Phase 5 grows from ~46 h to ~55 h |
| **Terraform 1.16 + azurerm 5.x** | azurerm 5.0 went GA on 2026-07-28 (resource providers are no longer registered automatically, deprecated resources removed); write-only arguments (Terraform ≥ 1.11) keep generated passwords out of state and plans |
| **No always-on Azure Container Registry** | ACR Basic would be ~1/6 of the budget; the app images are public on GHCR already (D19) and contain no secrets; models go to a private Azure Files share. ACR stays a Terraform flag |
| **Web on Static Web Apps Free**, not in a container | A landing page that scales to zero would itself be cold; SWA Free costs nothing and brings TLS and two custom domains |
| **Worker as an event-driven Container Apps job** | An HTTP-scaled AI service can be scaled to zero in the middle of a job; jobs are billed only while they run |
| **Qdrant Cloud free tier** for the lean demo, with keepalive and snapshots | Qdrant doesn't support network file systems, so Qdrant on Container Apps with Azure Files is out; the free cluster is suspended after a week unused and deleted after four weeks |
| **Phoenix self-hosted on Container Apps** as the one trace store | Phoenix's hosted cloud tier is no longer listed (Arize AX Free: 25k spans/month, 15 days); Log Analytics keeps platform logs only |
| **AKS Gateway = Traefik**, as in k3d | `approuting-istio` is GA since AKS 20260428, but parity with the P4 charts comes first; recorded as the alternative |
| **AKS minor chosen at M5.0** | 1.37 (the k3d pin) reaches community end of life in October 2027, right when Phase 5 runs; 1.38 is GA on AKS from February 2027 |
| **GitHub App replaces both PATs; its key never leaves Key Vault** | Installation tokens live 1 h and can be narrowed to one repo and a few permissions per request |
| **Managed / workload identity replaces the Azure service-principal secret** | No long-lived Azure credential anywhere, also not in GitHub |
| **Daily cap + per-key OpenRouter limit** before the URL goes public | Anyone can ask questions on a public URL; OpenRouter keys support a credit limit with a daily reset |
| **Let's Encrypt staging on ephemeral runs** | Re-creating the same certificate each run hits the 5-per-week limit for an identical name set; lifetimes are moving from 90 to 64 to 45 days |

---

## 0. Roadmap context

| Phase | Theme | Core hours | Result |
|---|---|---|---|
| 1 | Foundation + RAG slice + eval + tracing | ~76 | Streamed, cited answers; retrieval metrics; Phoenix traces; CI green |
| 2 | Agent | ~99 | Agent with MCP tools, approvals, conversations, audit, agent eval; taxonomy + gap signals |
| 3a | Retrieval quality, sub-topics & skills | ~75 | Hybrid + rerank + contextual + code-aware RAG, gated alias swap, priorities, skills |
| 3b | Evaluation, safety, cost, KB curator | ~76 | Judge gate, guardrails, ACL, cascade + cache, memory, compaction, curator (L2) |
| 4 | Kubernetes | ~46 | Whole stack on k3d from Helm charts, Gateway API + TLS, operators, hardening, Argo CD, read-only K8s tool, refresh CronJob (L3) |
| **5 (this doc)** | **Azure** | **~55** | Lean always-on demo (Container Apps + SWA) within ~30 USD/month; ephemeral AKS from a workflow via Argo CD; OIDC, managed/workload identity, Key Vault, GitHub App; workflow integration (option) |
| 6 | MLOps, local models, polish | ~63 | Distilled CPU reranker rolled out via an MLflow alias, local-vs-API benchmark on the M1, system card, supply chain, BFF, v1.0 |

Details for Phase 6: `plan-phase-6.md`.

---

## 1. Goal and demo script

**Goal.** By the end of Phase 5 the project runs in Azure in two shapes, both from the same repo and CI. The **lean
demo** is always reachable: the Angular app on Static Web Apps; NestJS, the AI service, Keycloak, the GitHub MCP server
and Phoenix on Container Apps scaled to zero; Postgres Flexible Server (B1ms); Qdrant Cloud free tier — for ~30 USD a
month, with hard limits on token spend. The **ephemeral AKS showcase** is created by a workflow, deployed by Argo CD from
the Phase 4 charts, smoke-tested and destroyed again. Nothing in the system holds a long-lived secret it could leak:
GitHub reaches Azure through OIDC, apps through managed or workload identity, secrets live in Key Vault, and GitHub
access goes through a GitHub App.

**Acceptance demo**

1. Open `https://kb.example.dev` after a quiet hour → the page loads at once and shows "waking up the demo"; login is
   ready in < 90 s (p95, measured) → sign in as guest → a cited answer streams.
2. As guest: no write, curator or upload tools are offered; the 11th question within an hour → limit message; with the
   test flag "daily cap reached" → a fixed "demo budget used up" answer without any LLM call.
3. With a reviewer account: an agent turn with GitHub read tools → the audit row shows the GitHub App installation token
   (repo, permissions, expiry); after approval, an issue is created in the sandbox repo.
4. *"What is in our Azure resource group, and why did ADR-0006 pick that region?"* → Azure MCP authenticated by the AI
   service's managed identity (Reader on two resource groups) + ADR citation.
5. `https://traces.kb.example.dev` (Keycloak login, editor+) → the trace of step 3 incl. MCP spans and token cost.
6. `gh workflow run e2e-aks.yml` → AKS (Free tier, arm64 nodes) comes up, Argo CD syncs platform → data → auth → apps
   with `values-aks.yaml`, External Secrets pulls the §7.2 secrets from Key Vault via workload identity, cert-manager
   issues staging certificates over DNS-01, Qdrant is restored from the latest cloud snapshot, Playwright smoke and
   retrieval-eval smoke pass, the cluster is destroyed; the job summary shows duration and estimated cost (< 1 USD).
7. Cancel a run before its destroy step → the hourly janitor deletes the expired cluster; a test budget alert (50 %)
   arrives by e-mail.
8. On the Mac: AKS-MCP (stdio, read-only) against a running e2e cluster answers *"Which pods restarted, and why?"*.
9. Scheduled jobs: the weekly refresh (L3) runs as a Container Apps job and its changes go through the promotion gates;
   the weekly Qdrant snapshot lands in Blob storage; the daily job keeps the free cluster from being suspended.
10. A PR touching `infra/terraform/` → `fmt`, `validate`, `tflint`, `trivy config` and a `terraform plan` from a
    read-only identity as a PR comment; after merge, `apply` waits for approval in the `infra` environment.
11. Cost view: month-to-date ≤ 30 USD and the forecast within budget; the repository has **no Actions secrets**.

---

## 2. Scope

**In scope**
- Subscription setup: region and quotas (ADR-0006), resource providers, resource groups, tags, budget and alerts
- Terraform: bootstrap (state), `shared`, `demo` and `e2e` stacks, CI with plan/apply gates and drift detection
- Identity: GitHub OIDC federation, user-assigned managed identities, AKS workload identity, Key Vault RBAC, GitHub App
- Data: Postgres Flexible Server (private access), Qdrant Cloud free tier with quantization, snapshots, keepalive
- Lean demo: Container Apps environment, apps and jobs, models on Azure Files, Static Web Apps, custom domains, wake-up
  flow, deploy workflow with rollback
- Public demo access: Keycloak production config, guest and reviewer roles, limits, daily cap
- Ephemeral AKS: cluster per run, Argo CD bootstrap, External Secrets, cert-manager + Let's Encrypt (DNS-01), smoke,
  destroy, TTL janitor
- Cloud observability: Phoenix on Container Apps, Log Analytics with a cap, alerts
- MCP in the cloud: public own MCP endpoint, Azure MCP via managed identity, AKS-MCP local demo
- Runbook, README "Live demo" section, cost review, system-card notes

**Out of scope (deferred, with target)**
- Image scanning, SBOMs, image signing → **6** (IaC scanning starts here)
- BFF cookie pattern (would remove browser-held tokens and CORS) → **6**
- Workflow integration → **5, option** (D107)
- Front Door / WAF, private AKS, HA or multi-region, Azure Firewall egress filtering → not planned (cost)
- Managed Prometheus / Grafana → not planned; Phoenix + Log Analytics are enough for this demo
- GPU nodes, serverless GPU → not planned (API models only)
- CloudNativePG Barman Cloud backups → dropped (managed backups replace them; CloudNativePG stays local)
- Self-registration with e-mail verification → later decision, needs an e-mail service

---

## 3. Decisions

Numbering continues from `plan-phase-4.md` (D88). Status: **N** = new · **C** = changes an earlier decision (named).

| # | St. | Topic | Decision | Why / alternatives |
|---|---|---|---|---|
| D89 | N | Subscription layout & quotas | Region from ADR-0006 (Germany West Central assumed, West Europe fallback). Persistent resource groups `rg-kb-shared` (state, network, Key Vault, Log Analytics, storage, DNS, identities, Postgres) and `rg-kb-demo` (Container Apps, Static Web Apps); `rg-kb-e2e` holds only ephemeral clusters. Tags `project=kb-agent`, `env`, `owner`, and `expires-at` on every e2e resource. Quota request at M5.0: 8 vCPU of the Dpsv6 family (arm64) and 8 vCPU Dasv6 (amd64 fallback). Resource providers registered explicitly in Terraform (azurerm 5 no longer does it). (ADR-0037) | Two persistent groups split "rarely changes" from "redeployed often"; one e2e group lets the e2e identity stay scoped to it. |
| D90 | N | Terraform | **Terraform 1.16.x**, **azurerm 5.x** (pinned at M5.0), plus `azuread` and `random`. Stacks `bootstrap` (state storage, run once from the Mac), `shared`, `demo`, `e2e` (one state key per run). Remote state in Blob with Entra auth only (shared keys off), blob-lease locking, versioning and soft delete. Generated passwords via `ephemeral "random_password"` and write-only arguments (`value_wo`, `administrator_password_wo`) so they never enter state or plans. Modules only where reused (`aca-app`, `federated-identity`). CI: `fmt`, `validate`, `tflint`, `trivy config`; plan on PRs as a comment; apply on `main` behind environment approval; weekly drift plan with `-detailed-exitcode`. (ADR-0038) | Terraform is in most job postings; Bicep would be Azure-only. Write-only arguments remove the classic "secrets in state" problem. |
| D91 | C (D37) | Identities | No long-lived Azure secret. **GitHub → Azure via OIDC** with four user-assigned identities and environment-scoped federated credentials: `id-gh-plan` (PRs, read-only), `id-gh-apply` (`infra`), `id-gh-deploy` (`demo`), `id-gh-e2e` (`e2e`). **Apps:** one user-assigned identity per Container App group; Key Vault access per secret (RBAC at secret scope). **AKS:** workload identity; the `e2e` stack adds federated credentials for the External Secrets, cert-manager and ai-service service accounts (the issuer URL changes per cluster) and deletes them on destroy. The service-principal secret `kb-azure-sp` is removed. Role table in §7.3. (ADR-0039) | Least privilege per pipeline and per app; nothing to rotate or leak. |
| D92 | C (D37) | GitHub access | **GitHub App `kb-agent-bot`**, installed on `kb-agent` (contents, issues, actions, pull requests, metadata: read) and on the sandbox repo (issues: write). The AI service mints installation tokens per tool scope and narrows them in the token request (`repositories`, `permissions`): read token for the main repo, `issues:write` only for the sandbox. Tokens are cached until 5 min before their 1 h expiry and never logged; the audit row records repo, permissions and expiry. The App JWT is signed by Key Vault (`sign`, RS256) with an imported, non-exportable key; fallback: the PEM as a Key Vault secret. The GitHub MCP server gets the token per request (A35). Webhooks off unless the workflow option is chosen. Replaces `kb-github-read` and `kb-github-sandbox`. (ADR-0040) | Short-lived, narrowly scoped tokens; the private key can't be copied out of the vault. Fine-grained PATs expire and are tied to your user. |
| D93 | N | Lean demo platform | **Container Apps** in a workload-profiles environment with the Consumption profile only, VNet-integrated (`/27` subnet), logs to Log Analytics. Apps with `minReplicas: 0`: `api` (0.5 vCPU / 1 GiB, max 2), `ai-service` (2 vCPU / 4 GiB, max 1, startup probe), `keycloak` (1 vCPU / 2 GiB), `github-mcp` (0.25 / 0.5, internal ingress), `phoenix` (0.5 / 1, D98). **Web** on **Static Web Apps Free** with a per-environment `config.json`; api CORS allows only the web origin. Images from GHCR, pinned by digest, `linux/amd64` (Container Apps runs amd64 only, A30). Custom domains with free managed certificates (§7.1). **Wake-up flow:** the landing page calls `api /health/wake` (which wakes ai-service and Phoenix) and Keycloak's discovery document in parallel, shows progress, then starts the login. The public host of ai-service serves only `/mcp` and its well-known path (host guard middleware); every other route stays internal and still requires the exchanged JWT. Terraform owns the configuration, the deploy workflow owns the image digest (`ignore_changes` on the image). (ADR-0041) | Pay-per-use with a monthly free grant (180,000 vCPU-s, 360,000 GiB-s, 2 M requests); ~0 USD at demo traffic. AKS always-on would cost more than the whole budget. |
| D94 | C (D81, D82) | Models in the cloud | Container Apps has no image volumes → models on a private **Azure Files** share `models`, mounted read-only at `/models/<set>` (same layout as the P4 model images, so `MODELS_DIR` is unchanged); filled by the `models-sync` workflow; gated or non-commercial models never public. AKS mounts the same share as a static read-only PersistentVolume (D81's PVC path). The cloud uses the `k3d-lite` model set (CPU reranker, Prompt Guard 22M). An ONNX int8 query encoder for bge-m3 is adopted only if golden `test` hit@5 drops ≤ 0.01 against fp32 (document embeddings stay fp32). Cold-start budget: p95 < 90 s until login is possible. Fallback: models baked into a private image in ACR (`acr_enabled`). (ADR-0042) | Keeps images small and public, and model versions independent of app releases. |
| D95 | C (D53, D82, D87) | Jobs on Container Apps | `ai-worker`: **event-driven job** with a KEDA `postgresql` rule on the Procrastinate queue (`todo` > 0), max 1 execution, own entry point that exits when the queue is empty (A32), 2 vCPU / 4 GiB, models from Files, replica timeout 2 h, 1 retry; a dedicated `kb_scaler` role may only count queue rows. ai-service runs with `JOBS_INPROCESS_WORKER=false`. Scheduled jobs: `kb-refresh` (weekly, the P4 client image → `POST /v1/curator/refresh`), `kb-daily` (Qdrant keepalive query, guest-data cleanup), `kb-qdrant-snapshot` (weekly → Blob, keep 4). Manual job `kb-migrate` (Drizzle `app`, `ai` schema, Procrastinate, roles) started by the deploy workflow inside the VNet. (ADR-0041) | Background work survives scale-to-zero of the app; queue-driven scaling is the KEDA pattern from job postings. |
| D96 | C (D80) | Postgres | **Azure Database for PostgreSQL Flexible Server**, Burstable **B1ms** (1 vCPU, 2 GiB), Postgres 17, 32 GiB, 7-day point-in-time backups, private access (delegated subnet + private DNS zone), TLS required. Databases `keycloak`, `app`, `ai`, `phoenix`; one role per service with the P4 grants (`audit_log` INSERT/SELECT only); the admin password is written to Key Vault by a write-only argument and used only by `kb-migrate`. AKS e2e runs use `*_e2e` databases on the same server, created and dropped by a hook Job as `kb_e2e_admin` (CREATEDB, CREATEROLE — since Postgres 16 it can manage only the roles it created, so the demo databases stay out of reach), never as the server admin; CloudNativePG stays the k3d path and the AKS fallback flag. Stop/start is a cost lever only (a stop lasts at most 7 days and takes the demo down). (ADR-0043) | Managed backups and patching; the cheapest always-on piece of the stack. The external-DB switch from D80 gets exercised on AKS. |
| D97 | C (D54, D56) | Qdrant hosting | Lean demo: **Qdrant Cloud free tier** (1 node, 1 GB RAM, 0.5 vCPU, 4 GB disk) in the EU region closest to ADR-0006. Collection with int8 scalar quantization in RAM and original vectors on disk, accepted by the eval gate. Granular API keys: read-only for ai-service, read-write for the worker and the snapshot job. `kb-daily` keeps it active; `kb-qdrant-snapshot` copies a weekly snapshot to Blob; every e2e run restores the latest snapshot into in-cluster Qdrant (= DR drill). Rebuild from stored originals (D52) timed once; thanks to the D60 context cache it costs no tokens. (ADR-0044) | Free and managed. Qdrant on Container Apps would need Azure Files, which Qdrant doesn't support; a paid cluster breaks the budget. |
| D98 | C (P1 tracing) | Cloud observability | **Phoenix self-hosted on Container Apps** (scale-to-zero, `phoenix` database, auth on): login via Keycloak OIDC with role mapping (editor → MEMBER, admin → ADMIN), a system API key for OTLP over HTTP. One trace store for the lean demo and the e2e runs (projects `demo`, `e2e`). Container logs to Log Analytics (5 GB/month free per billing account, daily cap 0.15 GB, 31 days); metric alerts for api 5xx, job failures and Postgres CPU credits. Application Insights not used for now; OTLP exporters keep it open. (ADR-0045) | Keeps the LLM-specific trace UI and eval workflow from Phase 1; a second trace store would split the data. |
| D99 | N | DNS, TLS, AKS gateway | Own domain (A38) with Azure DNS zones `kb.example.dev` and the delegated child zone `e2e.kb.example.dev`. Lean demo: managed certificates of SWA and Container Apps (free, auto-renewed). AKS: **Traefik** with the Gateway provider (the P4 Gateway and HTTPRoutes unchanged), A records set by the workflow, **cert-manager** ACME DNS-01 on the child zone via workload identity (DNS Zone Contributor on that zone only); **Let's Encrypt staging** by default, production only for `showcase` runs (≤ 2 per week). Without an own domain: default hostnames, which change when the environment is re-created (issuer and redirect URIs follow; documented), and the P4 local CA on AKS. Alternative recorded: AKS app routing `approuting-istio` with Key Vault certificates. (ADR-0046) | Stable hostnames keep the Keycloak issuer stable; the child zone confines what the cluster can change. |
| D100 | C (D36, D79) | Keycloak in the cloud | Container Apps: Keycloak 26.x **optimized image** built in CI (`kc.sh build`: Postgres, health, metrics; public on GHCR, no secrets), production mode, `hostname=https://auth.kb.example.dev`, `proxy-headers=xforwarded`; realm import at startup from the P4 realm JSON with environment placeholders (create-only); backends use the internal app address (`KEYCLOAK_INTERNAL_URL`) while `iss` stays public. Master-realm admin with OTP, brute-force detection on, admin console not exposed on the public host where possible (A39); changes by script through a manual `kcadm` job. Access tokens 5 min, SSO session 8 h, self-registration off. AKS: Keycloak Operator as in P4 with the external `keycloak_e2e` database. (ADR-0031 updated) | Same realm definition in all environments; the optimized build shortens cold starts. |
| D101 | N | Public demo access & limits | No self-registration. **Guest login:** shared `guest` account (role `viewer`: KB answers and read tools only; no writes, curator, memory or uploads), credentials on the landing page; guest conversations are scoped to the Keycloak session (`sid`) and deleted after 24 h; guest questions never feed gap signals or the feedback loop (protects the curator from steered gaps). **Reviewer accounts:** invite-only, created by you with a temporary password, role `editor`. Limits in `config/demo.yaml` (§7.9): per user and per guest session, max 2 concurrent agent runs, cheapest model route for guests; a **global daily token cap** (default 0.30 USD) checked before every LLM call; a dedicated OpenRouter key for the cloud with a credit limit and **daily reset** as the hard backstop. Landing page and chat state that answers come from an AI at the first interaction (EU AI Act Art. 50, enforceable since 2026-08-02). (ADR-0047) | A public URL invites token drain and injection attempts; limits are enforced in code and again at OpenRouter. |
| D102 | N | Ephemeral AKS showcase | Workflow `e2e-aks.yml` (manual, weekly, on release tags; one run at a time): `e2e` stack → **AKS Free tier**, newest GA minor at M5.0 (k3d pin raised to the same minor if k3s has it), Azure CNI Overlay with the Cilium dataplane (enforces the P4 network policies), OIDC issuer + workload identity, Azure RBAC for Kubernetes, one pool of 2 × `Standard_D4ps_v6` (arm64; `D4as_v6` fallback) in `snet-aks-e2e` → Helm installs Argo CD → app-of-apps with `values-aks.yaml` and the P4 sync waves → External Secrets `ClusterSecretStore` on Key Vault → cert-manager + Traefik Gateway → Keycloak Operator → Qdrant restore Job → apps → smoke (Playwright demo through the Gateway, retrieval eval on the `dev` subset, agent smoke with the fake LLM plus one real call on the cheapest model) → destroy with `if: always()` → cost estimate in the job summary. **TTL:** `expires-at` = start + 3 h, job timeout 2 h, hourly janitor deletes expired clusters and their federated credentials. P4 egress proxy and PSA `restricted` unchanged. (ADR-0048) | The Kubernetes skills are shown on a real cluster for ~0.40 USD per hour of runtime instead of ~100+ USD/month always-on. |
| D103 | N | Cost guardrails | Budget 30 USD/month with alerts at 50 / 80 / 100 % actual and 100 % forecast (e-mail + action group); cost estimate per e2e run in the job summary; weekly `cost-report` workflow (Cost Management query) in the job summary; `demo-pause` workflow sets every app to `maxReplicas: 0` and disables the jobs. Monthly table in §7.8, levers L1–L4. (ADR-0037) | The budget is a hard project constraint; alerts alone react too late for a forgotten cluster, so TTL and janitor come first. |
| D104 | C (D19, D88) | CI/CD for the cloud | Multi-arch images on `main` → GHCR (amd64 for Container Apps, arm64 for AKS and the Mac), deployed by digest. Workflows: `infra-plan` (PR), `infra-apply` (`infra`), `deploy-demo` (release tag: `kb-migrate` → update app digests → smoke against the public URL → automatic roll-back to the previous digests on failure; digests recorded as a GitHub deployment), `e2e-aks`, `janitor` (hourly), `drift` (weekly), `cost-report` (weekly), `models-sync` (on model changes). The SWA deployment token is fetched at run time with the deploy identity, never stored. Third-party actions pinned by commit SHA. | Releases are reproducible and reversible; the "no Actions secrets" rule holds. |
| D105 | C (D38) | MCP in the cloud | Own MCP server public at `https://mcp.kb.example.dev/mcp` with the P2 OAuth flow (Keycloak, resource indicator), reviewer role only. Azure MCP Server (pinned, read-only, restricted namespaces) authenticates with the AI service's managed identity (`AZURE_CLIENT_ID`), on AKS with workload identity; Reader on `rg-kb-shared` and `rg-kb-demo` only. AKS-MCP stays a local stdio demo (v0.0.20 is stdio-only) against an e2e cluster with the AKS RBAC Reader role. ACA dynamic sessions only if the P3b sandbox option was done. | Same tools, no stored credential; the agent's Azure view is limited to the project. |
| D106 | C (D83) | Egress on Container Apps | Container Apps consumption has no hostname firewall (Azure Firewall would exceed the budget many times over) → **app-level allow-list** in the AI service's and api's HTTP clients (the same host list as the P4 proxy), outbound calls logged. AKS keeps the enforced proxy + network policies. The difference is stated in the system card. (ADR-0034 updated) | Honest about what a 30 USD platform can enforce. |
| D107 | N | Options gate | At M5.0: workflow integration (~22 h) only if Phase 4 finished within +10 % of its hours and the token budget holds; otherwise it moves to the P6 options. The three plan defaults (access policy, domain, workflow option) are confirmed in the same step. | Keeps Phase 5 from growing silently. |

---

## 4. Assumptions and open items

| # | Assumption | If wrong |
|---|---|---|
| A28 | Phase 4 is done; deviations recorded in `plan-phase-4.md` before M5.0 | Shift the schedule |
| A29 | The quota request (8 vCPU Dpsv6 or Dasv6) is granted within the first two weeks | e2e on B-series nodes from ADR-0006, or smaller nodes with the `ci` profile; M5.6 is scheduled last |
| A30 | Container Apps still runs `linux/amd64` images only | Nothing to do — CI already builds amd64 |
| A31 | A workload-profiles environment with only the Consumption profile has no fixed fee and accepts a `/27` VNet subnet | Consumption-only environment (`/23`), or no VNet and Postgres public access with TLS + firewall |
| A32 | The KEDA `postgresql` rule works for event-driven jobs, and the Procrastinate worker can stop when the queue is empty | Scheduled job every 15 min that drains the queue |
| A33 | azurerm 5.x offers write-only arguments for `azurerm_key_vault_secret` and the Postgres admin password | Passwords generated by a script straight into Key Vault; Terraform reads nothing secret |
| A34 | Qdrant Cloud free tier offers an EU region, Qdrant ≥ 1.19 with BM25 inference and granular API keys; the collection fits 1 GB RAM with int8 quantization | Client-side BM25 (FastEmbed); trim the corpus or decide on a paid cluster |
| A35 | The GitHub MCP server in HTTP mode accepts a per-request token | Sidecar that restarts it with a fresh token every 50 min |
| A36 | Azure Files read speed loads the CPU model set within the cold-start budget | int8 models; models baked into a private image (ACR flag) |
| A37 | The scale-in cool-down of ai-service can be set above 300 s | SPA heartbeat while a chat tab is open (costs active time) |
| A38 | An own domain is available (~10–15 USD/year at a registrar) | Default hostnames (D99) |
| A39 | Keycloak's admin console can be kept off the public host while the admin REST API stays usable for scripts | Master admin with OTP + brute-force detection only |
| A40 | Container Apps ingress streams SSE unbuffered, with a request timeout above the agent's 120 s run limit (D27) | Heartbeat events every 15 s; shorter run limit for guests |

**Still open (decided inside the milestones):** Qdrant Cloud region (M5.3), int8 query encoder yes/no (M5.4), cool-down
values (M5.4), daily cap value (M5.5), one real LLM call in the e2e smoke yes/no (M5.6), Phoenix retention (M5.7).
**Defaults to confirm at M5.0 (D107):** guest + invite-only access, own domain, workflow option.

---

## 5. Architecture (Phase 5)

```
 GitHub: repo kb-agent · sandbox repo · GHCR (public app images) · Actions (OIDC, no secrets)
    │ OIDC (federated credentials per environment)        ▲ installation tokens (GitHub App, narrowed per call)
    ▼                                                     │
 Azure subscription (budget 30 USD/month, region per ADR-0006)
 ┌─ rg-kb-shared ─────────────────────────────────────────────────────────────────────────────────┐
 │ tfstate (Blob, Entra auth) · Key Vault (secrets + non-exportable github-app-signing key)       │
 │ Log Analytics (daily cap) · Storage: Files `models` (ro mounts) · Blob `snapshots`             │
 │ VNet 10.40.0.0/16: snet-aca /27 · snet-pg (delegated) · snet-aks-e2e /24                       │
 │ Postgres Flexible B1ms (private): keycloak · app · ai · phoenix [· *_e2e during runs]          │
 │ Azure DNS: kb.example.dev · e2e.kb.example.dev (child) · private DNS for Postgres              │
 │ Identities: id-gh-{plan,apply,deploy,e2e} · id-kb-{api,ai,jobs,keycloak,phoenix,eso,certmgr}   │
 └────────────────────────────────────────────────────────────────────────────────────────────────┘
 ┌─ rg-kb-demo (always on, scale-to-zero) ────────────────────────────────────────────────────────┐
 │ Static Web Apps Free ── https://kb.example.dev (Angular, wake-up page, guest login)            │
 │ Container Apps environment (Consumption profile, VNet):                                        │
 │   api ── api.kb.example.dev          ai-service ── mcp.kb.example.dev/mcp (host guard)         │
 │   keycloak ── auth.kb.example.dev    phoenix ── traces.kb.example.dev   github-mcp (internal)  │
 │   jobs: ai-worker (KEDA postgresql) · kb-refresh (weekly) · kb-daily · kb-qdrant-snapshot      │
 │         (weekly) · kb-migrate / kcadm (manual)                                                 │
 └────────────────────────────────────────────────────────────────────────────────────────────────┘
 ┌─ rg-kb-e2e (ephemeral, TTL 3 h) ───────────────────────────────────────────────────────────────┐
 │ AKS Free · 2 × D4ps_v6 (arm64) · Cilium · workload identity · Argo CD → P4 charts (values-aks) │
 │ External Secrets ← Key Vault · cert-manager (LE staging, DNS-01) · Traefik Gateway             │
 │ https://e2e.kb.example.dev · Qdrant in-cluster (restored snapshot) · *_e2e databases           │
 └────────────────────────────────────────────────────────────────────────────────────────────────┘
 Outside Azure: Qdrant Cloud free (EU) · OpenRouter (cloud key with daily limit) · GitHub API
```

| Component | Change in Phase 5 |
|---|---|
| web | Static build on SWA Free; `config.json` with cloud hosts; wake-up page |
| api | Container App; CORS for the web origin; guest scoping, limits, daily-cap check (D101); app-level egress allow-list |
| ai-service | Container App; models from Files; no in-process worker; host guard for `/mcp`; GitHub App token broker; Azure MCP via managed identity |
| worker | Event-driven job (KEDA) instead of a Deployment or in-process worker |
| Keycloak | Optimized image; realm import at startup; public issuer + internal backchannel |
| Postgres | Flexible Server, private; `*_e2e` databases for AKS runs |
| Qdrant | Qdrant Cloud free tier (demo); in-cluster restored from snapshots (AKS) |
| Phoenix | Container App with auth and Keycloak login; receives traces from both environments |
| New | GitHub App, Key Vault, Terraform stacks, e2e workflow + janitor, cost workflows |

**Request path (lean demo):** browser → SWA (static files) → `api.kb.example.dev` (Container Apps ingress, managed
certificate) → ai-service (internal address) → Postgres (private), Qdrant Cloud (HTTPS, read-only key), OpenRouter. SSE
passes the Container Apps ingress unbuffered (A40).

**Cold path:** after scale-to-zero, the first visit loads the static page from SWA; the page wakes api (which wakes
ai-service and Phoenix) and Keycloak in parallel and only then starts the login.

**Token path:** issuer `https://auth.kb.example.dev/realms/kb`; api and ai-service check `iss` against it and call JWKS and
token exchange through `KEYCLOAK_INTERNAL_URL` (the Keycloak app's internal address in the environment).

**Secret path:** Key Vault → Container Apps secret references (user-assigned identity) → environment variables; on AKS
Key Vault → External Secrets → Kubernetes Secrets with the P4 names (§7.2).

---

## 6. Repository layout (additions)

```
kb-agent/
├─ infra/terraform/
│  ├─ bootstrap/                      # state storage account + container (run once from the Mac)
│  ├─ shared/                         # providers, network, Key Vault, Log Analytics, storage, DNS, identities,
│  │                                  # federated credentials, Postgres, budgets, alerts
│  ├─ demo/                           # Container Apps environment, apps, jobs, SWA, custom domains
│  ├─ e2e/                            # AKS cluster, workload-identity credentials, DNS records (state key per run)
│  └─ modules/{aca-app,federated-identity}/
├─ infra/k8s/aks/                     # ClusterSecretStore, ExternalSecrets, ClusterIssuers (staging/prod),
│                                     # models PV/PVC, e2e database hook Job, Qdrant restore Job
├─ charts/kb-agent/values-aks.yaml    # filled in (stub since P4)
├─ images/keycloak/Dockerfile         # optimized build (kc.sh build) + realm JSON
├─ config/demo.yaml                   # access policy, limits, daily cap (D101)
├─ .github/workflows/{infra-plan,infra-apply,deploy-demo,e2e-aks,janitor,drift,cost-report,models-sync,demo-pause}.yml
├─ scripts/azure/{bootstrap.sh,quota-check.sh,models-sync.sh,secrets-seed.sh,openrouter-cloud-key.sh,
│                 e2e-bootstrap.sh,run-summary.sh,kcadm.sh,pause.sh}
└─ docs/runbooks/azure.md             # deploy, rollback, rotate, restore, pause, teardown, cost
```

---

## 7. Contracts (draft — Terraform, rendered manifests and the values schema are authoritative)

`example.dev` stands for your domain (A38); `<owner>` for your GitHub account.

### 7.1 Hostnames

| Host | Serves | TLS |
|---|---|---|
| `kb.example.dev` | SWA: Angular app, wake-up page | SWA managed certificate (apex via alias record) |
| `api.kb.example.dev` | Container App `api` (`/api/*`, SSE) | Container Apps managed certificate |
| `auth.kb.example.dev` | Container App `keycloak` (realm `kb`) | Container Apps managed certificate |
| `mcp.kb.example.dev` | Container App `ai-service`: only `/mcp`, `/.well-known/oauth-protected-resource/mcp` | Container Apps managed certificate |
| `traces.kb.example.dev` | Container App `phoenix` (UI + OTLP `/v1/traces`) | Container Apps managed certificate |
| `e2e.kb.example.dev`, `auth.`/`mcp.e2e.kb.example.dev` | AKS Gateway (P4 routes: `/`, `/api`, Keycloak, MCP) | cert-manager, Let's Encrypt staging (prod for showcase runs) |

### 7.2 Secrets: Key Vault ↔ P4 secret names

| Kubernetes Secret (P4 §7.4) / Container Apps secret | Key Vault | Used by |
|---|---|---|
| `kb-openrouter` | `openrouter-api-key-cloud` (key with daily limit) | ai-service, ai-worker |
| `kb-keycloak-clients` | `kc-client-kb-api`, `kc-client-kb-ai`, `kc-client-kb-refresh`, `kc-client-phoenix` | api, ai-service, kb-refresh, Keycloak import, Phoenix |
| `kb-approval-signing` | `approval-hmac-key` | ai-service |
| `kb-github-app` (**new**, replaces `kb-github-read` / `kb-github-sandbox`) | `github-app-id`, `github-installation-main`, `github-installation-sandbox` + **key** `github-app-signing` | ai-service (sign permission only) |
| `kb-azure-sp` | — **removed** (managed / workload identity) | — |
| `kb-qdrant` | `qdrant-url`, `qdrant-api-key-read`, `qdrant-api-key-write` | ai-service (read); ai-worker, snapshot job (write) |
| `kb-pg-*` | `pg-uri-keycloak`, `pg-uri-app`, `pg-uri-ai`, `pg-uri-phoenix`, `pg-uri-scaler`, `pg-admin-password`, `e2e-pg-uri-admin` | per service; server admin only for `kb-migrate`; `kb_e2e_admin` only for the e2e hook Job |
| `kb-phoenix` (**new**) | `phoenix-secret`, `phoenix-api-key`, `phoenix-admin-password` | Phoenix; api, ai-service, worker (OTLP key) |
| `kb-keycloak-admin` (**new**) | `keycloak-admin-password` | Keycloak bootstrap, `kcadm` job |
| `kb-models-files` (**new**, AKS only) | `models-storage-key` | static PersistentVolume |

e2e runs read `e2e-`-prefixed copies where values differ (realm client secrets, `*_e2e` database URIs). Seeded by
`scripts/azure/secrets-seed.sh` or Terraform write-only arguments; Qdrant and OpenRouter keys are created in their
consoles/APIs and written by the script.

### 7.3 Identities and role assignments

| Identity | Used by (federated subject) | Roles (scope) |
|---|---|---|
| `id-gh-plan` | `repo:<owner>/kb-agent:pull_request` | Reader (`rg-kb-shared`, `rg-kb-demo`) · Storage Blob Data Reader (`tfstate`) |
| `id-gh-apply` | `…:environment:infra` | Contributor (both persistent groups) · Role Based Access Control Administrator with a condition limiting assignable roles to this table · Storage Blob Data Contributor (`tfstate`) · Key Vault Secrets Officer |
| `id-gh-deploy` | `…:environment:demo` | Contributor (`rg-kb-demo`: app digests, job starts, SWA deployment token) · Storage File Data SMB Share Contributor (`models`, for `models-sync`) |
| `id-gh-e2e` | `…:environment:e2e` | Contributor (`rg-kb-e2e`) · Azure Kubernetes Service RBAC Cluster Admin (`rg-kb-e2e`, for the bootstrap) · Network Contributor (`snet-aks-e2e`) · Managed Identity Contributor (`id-kb-eso`, `id-kb-certmgr`, `id-kb-ai`, `id-kb-jobs`) · DNS Zone Contributor (`e2e.kb.example.dev`) · Storage Blob Data Contributor (`tfstate`) |
| `id-kb-api` | Container App `api` | Key Vault Secrets User (its secrets) |
| `id-kb-ai` | `ai-service`, `ai-worker`; AKS SA `kb/ai-service` | Key Vault Secrets User (its secrets) · Key Vault Crypto User (`github-app-signing`, sign) · Reader (`rg-kb-shared`, `rg-kb-demo`) for Azure MCP |
| `id-kb-jobs` | `kb-refresh`, `kb-daily`, `kb-qdrant-snapshot`, `kb-migrate`; AKS restore Job | Key Vault Secrets User (its secrets) · Storage Blob Data Contributor (`snapshots`) |
| `id-kb-keycloak` · `id-kb-phoenix` | Container Apps `keycloak` · `phoenix` | Key Vault Secrets User (their secrets) |
| `id-kb-eso` | AKS SA `external-secrets/external-secrets` | Key Vault Secrets User (`e2e-*` and shared e2e secrets) |
| `id-kb-certmgr` | AKS SA `cert-manager/cert-manager` | DNS Zone Contributor (`e2e.kb.example.dev`) |

Azure Container Registry roles appear only if `acr_enabled` is switched on (D94 fallback).

### 7.4 Terraform excerpt — `ai-service` and `ai-worker` (`infra/terraform/demo`)

```hcl
module "ai_service" {
  source        = "../modules/aca-app"
  name          = "ai-service"
  image         = "ghcr.io/<owner>/kb-agent-ai@${var.bootstrap_digests.ai}"   # deploy workflow owns later digests
  cpu           = 2
  memory        = "4Gi"
  min_replicas  = 0
  max_replicas  = 1
  identity_id   = data.terraform_remote_state.shared.outputs.identities.ai.id
  ingress       = { external = true, target_port = 8000, custom_domain = "mcp.kb.example.dev" }
  storage_mount = { name = "models", share = "models", path = "/models", read_only = true }
  probes        = { startup = { path = "/health/startup", failure_threshold = 30, period_s = 5 } }
  env = {
    JOBS_INPROCESS_WORKER = "false"
    MODELS_DIR            = "/models"
    KEYCLOAK_INTERNAL_URL = local.keycloak_internal_url
    AZURE_CLIENT_ID       = data.terraform_remote_state.shared.outputs.identities.ai.client_id
  }
  secrets = {                                        # Key Vault references, resolved by the identity
    OPENROUTER_API_KEY = "openrouter-api-key-cloud"
    QDRANT_API_KEY     = "qdrant-api-key-read"
    DATABASE_URL       = "pg-uri-ai"
  }
}

resource "azurerm_container_app_job" "ai_worker" {
  name                         = "ai-worker"
  container_app_environment_id = azurerm_container_app_environment.demo.id
  replica_timeout_in_seconds   = 7200
  replica_retry_limit          = 1
  event_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
    scale {
      min_executions              = 0
      max_executions              = 1
      polling_interval_in_seconds = 60
      rules {
        name             = "procrastinate-todo"
        custom_rule_type = "postgresql"
        metadata = {
          query            = "SELECT count(*) FROM procrastinate_jobs WHERE status = 'todo'"
          targetQueryValue = "1"
          host = local.pg_host, port = "5432", dbName = "ai", userName = "kb_scaler", sslmode = "require"
        }
        authentication { secret_name = "pg-password-scaler", trigger_parameter = "password" }
      }
    }
  }
  # template: same image as ai-service, command ["python", "-m", "kb_ai.worker", "--until-empty"], models mount
}
```

### 7.5 Values (excerpt of `values-aks.yaml`)

```yaml
global:
  domain: e2e.kb.example.dev
  keycloak: {issuer: https://auth.e2e.kb.example.dev/realms/kb, internalUrl: http://keycloak-service.kb-auth:8080}
  database:
    mode: external                                  # D80 switch
    host: psql-kb.private.postgres.database.azure.com
    sslmode: require
    databases: {keycloak: keycloak_e2e, app: app_e2e, ai: ai_e2e}
  egressProxy: {url: http://egress-proxy:3128, noProxy: ".svc,.cluster.local,localhost,127.0.0.1"}
  gateway: {className: traefik, clusterIssuer: letsencrypt-staging}
  secrets: {provider: externalSecrets, store: kb-keyvault}
  otlp: {endpoint: https://traces.kb.example.dev/v1/traces, project: e2e}
api:       {replicas: 2, hpa: {enabled: true}}
aiService:
  worker: {separate: true}
  models: {source: pvc, pvc: {claimName: models-azurefile}}
  serviceAccount: {annotations: {azure.workload.identity/client-id: "<id-kb-ai client id>"}}
qdrant:   {restore: {enabled: true, from: latest}}   # Job pulls the newest snapshot from Blob (id-kb-jobs)
phoenix:  {enabled: false}                           # traces go to the cloud Phoenix
argocd:   {enabled: true}
refresh:  {enabled: false}                           # the weekly refresh runs on Container Apps only
```

### 7.6 `e2e-aks.yml` (skeleton)

```yaml
on:
  workflow_dispatch: {inputs: {issuer: {type: choice, options: [staging, production], default: staging}}}
  schedule: [{cron: "17 5 * * 1"}]                 # weekly, Monday 05:17 UTC
  push: {tags: ["v*"]}
concurrency: {group: e2e-aks, cancel-in-progress: false}
permissions: {id-token: write, contents: read}
jobs:
  e2e:
    environment: e2e
    runs-on: ubuntu-24.04
    timeout-minutes: 120
    steps:
      - uses: actions/checkout@<sha>
      - uses: azure/login@<sha>                    # client-id / tenant-id / subscription-id are variables, not secrets
        with: {client-id: "${{ vars.AZ_CLIENT_ID_E2E }}", tenant-id: "${{ vars.AZ_TENANT_ID }}",
               subscription-id: "${{ vars.AZ_SUBSCRIPTION_ID }}"}
      - run: scripts/azure/e2e-apply.sh "${{ github.run_id }}"        # terraform e2e stack, expires-at = now + 3 h
      - run: scripts/azure/e2e-bootstrap.sh "${{ inputs.issuer || 'staging' }}"   # Argo CD, app-of-apps, wait healthy
      - run: pnpm e2e:smoke --base-url https://e2e.kb.example.dev                 # Playwright + eval smoke
      - if: always()
        run: scripts/azure/e2e-destroy.sh "${{ github.run_id }}"      # drops *_e2e DBs, destroys the stack
      - if: always()
        run: scripts/azure/run-summary.sh >> "$GITHUB_STEP_SUMMARY"   # duration, nodes, estimated cost
```

### 7.7 Environment changes

| Variable | Service | Cloud value |
|---|---|---|
| `DEMO_MODE` (new) | api, ai-service | `public` (guest rules, limits, daily cap) |
| `DEMO_DAILY_CAP_USD` (new) | ai-service | `0.30` |
| `CORS_ORIGINS` (new) | api | `https://kb.example.dev` |
| `PUBLIC_MCP_HOST` (new) | ai-service | `mcp.kb.example.dev` (host guard) |
| `EGRESS_ALLOWLIST` (new) | api, ai-service | the P4 proxy host list (D106) |
| `GITHUB_APP_ID`, `GITHUB_INSTALLATION_MAIN`, `GITHUB_INSTALLATION_SANDBOX`, `GITHUB_APP_KEY_ID` (new) | ai-service | App and installation ids; Key Vault key id |
| `AZURE_CLIENT_ID` (new) | ai-service | client id of `id-kb-ai` (Azure MCP, Key Vault sign) |
| `QDRANT_URL`, `QDRANT_API_KEY` | ai-service / worker | Qdrant Cloud URL; read key / write key |
| `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_HEADERS` | api, ai-service, worker | Phoenix `/v1/traces`; `authorization=Bearer <system key>` |
| `JOBS_INPROCESS_WORKER` | ai-service | `false` |
| `KEYCLOAK_INTERNAL_URL` | api, ai-service, kb-refresh | internal address of the Keycloak app |
| `GITHUB_TOKEN_*` PAT variables | ai-service, github-mcp | **removed** |

### 7.8 Monthly cost (USD, list prices, region per ADR-0006; re-checked in the pricing calculator at M5.0)

| Item | Sizing / assumption | USD / month |
|---|---|---|
| Postgres Flexible compute | B1ms, always on | ~15.0 |
| Postgres storage | 32 GiB (minimum); backups within the free allowance | ~4.0 |
| Container Apps — apps | scale-to-zero; ~40 demo sessions/month stay within the free grant | 0–3 |
| Container Apps — jobs | worker, refresh, daily, snapshot: minutes per week | < 1 |
| Static Web Apps | Free plan | 0 |
| Qdrant Cloud | free tier | 0 |
| Azure Files + Blob | models ~6 GiB, ≤ 4 snapshots, Terraform state | ~0.8 |
| Key Vault | operations only | < 0.1 |
| Log Analytics | < 5 GB/month (daily cap 0.15 GB) | 0 |
| Azure DNS | 2 public zones + 1 private zone | ~1.5 |
| Metric alerts | 3–5 rules | ~0.5 |
| Ephemeral AKS | ~0.40 USD/h (2 × D4ps_v6 at ~0.17 USD/h + load balancer, IP, disks) × ~4 h/month | ~1.6 |
| Domain | ~12 USD/year at a registrar (outside Azure) | ~1.0 |
| **Steady month** | | **~25–28** |
| Build months (Sep/Oct 2027) | + ~15 h of AKS iterations; Postgres only from week 2 | ~28–31 |

**Levers if the forecast passes 30 USD:** L1 stop Postgres at night (−~4.5) · L2 e2e every second week (−~0.8) ·
L3 default hostnames instead of the own domain (−~2.5) · L4 `demo-pause` (demo down, AKS still possible).
**Tokens are separate** (user-funded OpenRouter): the cloud key's daily limit of 0.30 USD caps the public demo at ~9 USD
a month in the worst case.

### 7.9 Demo access and limits (`config/demo.yaml`)

```yaml
access:
  self_registration: false
  guest:    {enabled: true, role: viewer, session_ttl_h: 24, memory: false, uploads: false, feeds_gap_signals: false}
  reviewer: {invite_only: true, role: editor}
limits:
  per_user:           {questions_per_hour: 20, questions_per_day: 100}
  per_guest_session:  {questions_per_hour: 10}
  guest_questions_per_day_total: 300
  concurrent_agent_runs: 2
  agent_max_steps_guest: 4
budget:
  daily_cap_usd: 0.30            # checked before every LLM call; OpenRouter key limit is the backstop
  on_exceeded: static_message
models:
  guest_route: cheap             # D70 cascade without escalation
```

---

## 8. Milestones and tasks

Order: M5.0 → M5.1 → M5.2 → M5.3 → M5.4 → M5.5 → M5.6 → M5.7 → M5.8 → M5.9. Hours are ideal single-person hours, ±30 %.

### M5.0 — Kick-off, quotas, spikes (~3 h)

- [ ] Record Phase 4 deviations; confirm the plan defaults and the options gate (D107)
- [ ] Quota check and request (Dpsv6 + Dasv6, 8 vCPU each) on day 1; register the resource providers
- [ ] **Spikes (≤ 30 min each):** workload-profiles environment fee + VNet (A31) · model load time from Azure Files in a
  Container App (A36) · KEDA `postgresql` job rule + worker stop on empty queue (A32) · Qdrant Cloud free cluster:
  region, version, BM25 inference, granular keys, RAM fit (A34) · write-only arguments in azurerm 5.x (A33) · GitHub MCP
  server with a per-request token (A35) · SSE, request timeout and cool-down on Container Apps (A37, A40)
- [ ] Pin Terraform 1.16.x, azurerm 5.x, azuread, random, the AKS minor, Azure MCP, Keycloak 26.x; cost table §7.8
  re-checked in the pricing calculator

**Acceptance:** quota request filed; spike results in the ADR-0037 … 0044 drafts; versions pinned.

### M5.1 — Terraform foundation (~9 h)

- [ ] `bootstrap`: state storage account (Entra auth only, shared keys off, versioning, soft delete), container
  `tfstate`; `scripts/azure/bootstrap.sh`
- [ ] `shared`: resource groups, VNet + subnets, Key Vault (RBAC mode, purge protection), Log Analytics (daily cap),
  storage (Files `models`, Blob `snapshots` with a lifecycle rule), DNS zones + delegation, private DNS zone, budgets +
  action group (D103)
- [ ] Postgres Flexible Server (D96) with the admin password via write-only argument into Key Vault
- [ ] `infra-plan` (fmt, validate, tflint, `trivy config`, plan → PR comment), `infra-apply` (environment approval),
  `drift` (weekly)
- [ ] GitHub environments `infra`, `demo`, `e2e` with protection rules; repository variables for ids — no secrets
- [ ] ADR-0037, ADR-0038

**Acceptance:** demo step 10; a CI check greps plan output and state for secret values (none); a test budget alert
fires.

### M5.2 — Identity, secrets, GitHub App (~6 h)

- [ ] Identities, federated credentials and role assignments (§7.3), incl. per-secret Key Vault scopes and the RBAC
  Administrator condition
- [ ] Key Vault secrets (§7.2) via write-only arguments and `secrets-seed.sh`; OpenRouter cloud key with limit + daily
  reset (`openrouter-cloud-key.sh`)
- [ ] GitHub App: create, install on both repos, import the key as non-exportable; token broker in the AI service
  (narrowed tokens, cache, audit fields) with a fake GitHub in tests; PATs revoked
- [ ] Azure MCP with the managed identity; `kb-azure-sp` and its service principal deleted
- [ ] ADR-0039, ADR-0040

**Acceptance:** demo step 3 (locally against the cloud identities until M5.4 deploys it); the repo has zero Actions
secrets; an audit row shows token repo, permissions and expiry;
`az role assignment list` matches §7.3; the old PATs fail.

### M5.3 — Data tier (~6 h)

- [ ] `kb-migrate` job: databases, roles (incl. `kb_scaler`), Drizzle, `ai` schema, Procrastinate
- [ ] Initial data: restore a `pg_dump` of the local `ai` database (stored originals + `chunk_context_cache`) → re-index
  job in the cloud → Qdrant Cloud (no LLM calls, D60 cache)
- [ ] Qdrant Cloud free cluster (region, version), granular keys → Key Vault; collection with int8 quantization and
  on-disk originals; eval gate: golden `test` hit@5 / nDCG@10 within 0.01 of the local collection
- [ ] `kb-qdrant-snapshot` → Blob; `kb-daily` keepalive; restore drill once into k3d from a cloud snapshot; rebuild from
  originals timed once
- [ ] ADR-0043, ADR-0044

**Acceptance:** cloud retrieval eval within 0.01 of local; re-index made zero LLM calls; snapshot in Blob; restore
drill passes.

### M5.4 — Lean demo on Container Apps + Static Web Apps (~11 h)

- [ ] Container Apps environment (Consumption profile, VNet, Log Analytics); `modules/aca-app`
- [ ] Apps: api, ai-service (host guard), keycloak (optimized image, realm import, internal URL), github-mcp
  (internal), phoenix — identities, Key Vault references, probes, scale rules, cool-down
- [ ] `models-sync` workflow fills the Files share; mount; cold-start measurement (p50/p95 per app); int8 query encoder
  decided by eval
- [ ] Jobs: ai-worker (KEDA), kb-refresh, kb-daily, kb-qdrant-snapshot, kb-migrate
- [ ] SWA Free: Angular build, `config.json`, wake-up page; CORS; custom domains + managed certificates
- [ ] `deploy-demo` workflow: migrate → update digests → smoke against the public URL → roll back on failure; SWA token
  fetched at run time
- [ ] App-level egress allow-list in api and ai-service (D106); ADR-0041, ADR-0042; ADR-0034 updated

**Acceptance:** demo steps 1 and 9; SSE streams through the Container Apps ingress; a release tag deploys, and a broken
image is rolled back automatically.

### M5.5 — Keycloak production config & demo access (~4 h)

- [ ] Keycloak: hostname, proxy headers, admin console off the public host (A39), master admin OTP, brute-force
  detection, token lifetimes, cloud redirect URIs, `phoenix` client with role claim in the ID token
- [ ] Guest account and session-scoped guest conversations; guest questions excluded from gap signals and feedback;
  cleanup in `kb-daily`
- [ ] `config/demo.yaml` limits; daily-cap check before every LLM call; friendly limit messages; OpenRouter key limit
  verified with a test key
- [ ] AI disclosure on the landing page and in the chat at the first interaction (EU AI Act Art. 50)
- [ ] Reviewer invite runbook; ADR-0047; ADR-0031 updated

**Acceptance:** demo step 2; the P3b red-team suite runs against the cloud URL with the guest role: no write, curator or
upload tool is reachable; a locked-out guest account recovers after the lockout window.

### M5.6 — Ephemeral AKS showcase (~9 h)

- [ ] `e2e` stack: AKS (D102), workload-identity credentials for External Secrets, cert-manager and ai-service, DNS
  records, `expires-at` tags
- [ ] `values-aks.yaml` (§7.5) and `infra/k8s/aks/`: ClusterSecretStore, ExternalSecrets with the P4 names,
  ClusterIssuers (staging/prod), models PV/PVC on Azure Files, `*_e2e` database hook Job, Qdrant restore Job
- [ ] `e2e-aks.yml`, `janitor.yml` (hourly), `run-summary.sh` with the cost estimate
- [ ] AKS checks: PSA `restricted`, network policies enforced by Cilium, egress through the proxy; `kube-linter` on the
  `values-aks` render; Argo CD app tree healthy
- [ ] ADR-0046, ADR-0048

**Acceptance:** demo steps 6–7; two consecutive green runs; a run with a failing smoke still destroys the cluster.

### M5.7 — Cloud observability (~3 h)

- [ ] Phoenix auth: Keycloak OIDC with role mapping, system API key for OTLP; exporters in api, ai-service and worker;
  e2e runs export to project `e2e`
- [ ] Log Analytics daily cap and retention; metric alerts (api 5xx, job failures, Postgres CPU credits) → action group
- [ ] ADR-0045

**Acceptance:** demo step 5; a trace from an e2e run appears in project `e2e`; Log Analytics ingestion stays below
0.15 GB/day for a week.

### M5.8 — MCP & agent tools in the cloud (~2 h)

- [ ] Public MCP endpoint with Keycloak OAuth tested with MCP Inspector and one external client (reviewer role)
- [ ] AKS-MCP stdio demo on the Mac against an e2e cluster (`az aks get-credentials`, AKS RBAC Reader, read-only)
- [ ] Agent eval tasks for Azure MCP with the managed identity (fixture + one live smoke)

**Acceptance:** demo steps 4 and 8.

### M5.9 — Cost & ops review, docs, exit demo (~2 h)

- [ ] Month-to-date cost vs. §7.8; levers applied if the forecast passes 30 USD; `cost-report` workflow
- [ ] `docs/runbooks/azure.md` (deploy, rollback, rotate secrets and the GitHub App key, restore Qdrant, pause,
  teardown); README "Live demo" section with diagram and cost table
- [ ] System-card notes: cloud data flows, guest retention, egress difference (D106), limits

**Acceptance:** demo step 11; the runbook covers every operation used in the demo script.

### Option (decided at M5.0, D107) — Workflow integration (~22 h)

| Part | Content | h |
|---|---|---|
| MCP surface | Skills as MCP prompts; `answer_from_kb` tool with citations on the public MCP endpoint | 4 |
| Headless runs API | `POST /v1/runs` (+ status, result); GitHub Actions OIDC tokens accepted through Keycloak federated client authentication (26.6); per-repo run budget | 7 |
| CI-failure triage | Workflow on failed CI → run with the triage skill → comment by the GitHub App (service-side token, no Actions secret) | 4 |
| ADR-based PR review | Workflow on PRs touching `docs/adr/` or `infra/` → review comment citing ADRs | 4 |
| Repo sync on merge | Push to `main` → code index refresh (`search_code`) through the worker job | 3 |

---

## 9. Schedule (8–10 h/week, 9 h used)

| Week | Focus |
|---|---|
| 1 | M5.0 kick-off (quota request on day 1), M5.1 bootstrap + `shared` |
| 2 | M5.1 Postgres + CI, M5.2 federation + Key Vault |
| 3 | M5.2 GitHub App + Azure MCP identity, M5.3 data tier |
| 4 | M5.4 lean demo → **public URL live (~late September 2027)** |
| 5 | M5.4 deploy workflow, M5.5 access & limits, start M5.6 |
| 6 | M5.6 ephemeral AKS, M5.7 observability, M5.8 MCP, M5.9 review → exit demo |
| — | **1 buffer week** |

**Cut line** (drop in this order): workflow option → AKS-MCP stdio demo → int8 query-encoder experiment → weekly e2e
schedule (manual and tag runs only) → Let's Encrypt production issuer (staging only) → Phoenix Keycloak login (API key +
admin password) → per-secret Key Vault scopes (per-identity vault scope) → `drift` workflow → `cost-report` workflow
(budget alerts stay) → own domain (default hostnames).
**Never cut:** no long-lived secrets (OIDC, managed/workload identity, GitHub App), secrets out of Terraform state,
budget alerts + TTL + janitor + destroy-always, daily cap + OpenRouter key limit before the URL is public, guest role
without write tools, private Postgres, eval gate on the cloud collection, Qdrant snapshots + keepalive, the pause and
teardown runbook.

---

## 10. Definition of Done (Phase 5)

- [ ] Demo script (§1) passes: lean demo reachable on the public URL, e2e workflow green twice in a row
- [ ] All versions pinned (Terraform, providers, AKS minor, images by digest); third-party actions pinned by SHA
- [ ] No Actions secrets; no long-lived Azure or GitHub credential; plan output and state free of secret values
- [ ] Every identity matches §7.3; Key Vault access per secret
- [ ] Cloud collection within 0.01 hit@5 / nDCG@10 of local; snapshot restore drill passed
- [ ] Guest role, limits and daily cap enforced and tested; red-team suite passes against the cloud URL
- [ ] Budget alerts, TTL, janitor and `demo-pause` tested; month-to-date ≤ 30 USD
- [ ] Traces from both environments in Phoenix; Log Analytics within its cap
- [ ] ADR-0037 … 0048 written; ADR-0031 and ADR-0034 updated; `docs/runbooks/azure.md` and README updated

---

## 11. Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Budget overrun (always-on pieces + a forgotten cluster) | Medium | TTL + janitor + destroy-always, budget alerts incl. forecast, levers L1–L4, `demo-pause` |
| Quota not granted in time | Medium | Requested on day 1; M5.6 scheduled last; B-series or smaller-node fallback |
| Qdrant Cloud free cluster suspended, deleted, or its terms change | Medium | Daily keepalive, weekly snapshots, restore drill in every e2e run, rebuild from originals without tokens |
| Cold starts make the demo feel broken | Medium–High | Wake-up page with progress, measured p95, longer cool-down, optimized Keycloak, lighter models, scheduled pre-warm before known demo dates |
| Public demo abuse (token drain, injection, account lockout) | Medium | Daily cap + key limit, guest role, red-team run against the cloud, brute-force settings, guest data deleted after 24 h |
| ai-service's public host exposes internal routes | Medium | Host guard middleware + exchanged JWT on every route + a test per route |
| Secrets in Terraform state or logs | Medium | Write-only arguments, Entra-only state access, grep check in CI, no secrets in GitHub |
| Let's Encrypt limits during e2e iterations | Medium | Staging by default; production ≤ 2 per week |
| Egress not enforced on Container Apps | Medium | App-level allow-list, outbound logging, documented difference; AKS enforces |
| Provider and platform churn (azurerm 5.x, AKS minors, Container Apps API versions) | Medium | Pinned versions, weekly drift plan, AKS minor chosen at M5.0 |
| GitHub App key misuse | Low | Non-exportable key, sign permission for one identity, rotation runbook |
| Azure Files model loading slow or unreliable | Medium | int8 models; baked private image as fallback (ACR flag) |
| Azure rabbit holes eat the AI time | Medium | Time-boxed spikes, cut line, buffer week |

---

## 12. Hand-off to Phase 6

- Image scanning (Trivy), SBOMs and signing for the GHCR images; IaC scanning already runs
- BFF cookie pattern would remove browser-held tokens and the cross-origin setup of the public demo
- MLflow (M6.1) runs locally by default; a cloud instance only after a cost check
- Fine-tuned reranker rollout (M6.3) reaches the cloud as a new model-set version on the Files share (D94), behind
  the promotion gate; no re-index needed
- Local models (M6.5) stay on the Mac; the cloud keeps API models
- System card v1: cloud data flows, guest retention, egress difference, limits, curation levels in use
- Demo video recorded against the public URL
- L4 (optional, after P6): guest questions are already excluded from gap signals (D101), one of its go/no-go conditions

---

## 13. Study-list coverage in Phase 5

| # | Topic | Where in Phase 5 |
|---|---|---|
| 5, 17 | Embedding benchmarking, retrieval evaluation | D94 int8 vs. fp32 query encoder; D97 quantized collection checked against golden `test` |
| 6 | Vector DB & ANN | D97 managed hosting, scalar quantization, snapshots and restore |
| 8, 43 | Idempotent ingestion, eval as gate | D95 queue-driven worker job; refresh with the same gates in the cloud; e2e eval smoke |
| 16 | Token & cost tracking | D101 global daily cap + key limit; D103 cost per e2e run |
| 18 | Tracing | D98 Phoenix for both cloud environments |
| 19 | Data privacy | D94 licensed models private; D106 egress; guest data retention |
| 20, 46 | Prompt injection, red teaming | M5.5 red-team suite against the public deployment |
| 30 | MCP | D105 public MCP endpoint, Azure MCP via managed identity, AKS-MCP |
| 31 | Tool / MCP auth | D91 OIDC + workload identity; D92 narrowed GitHub App tokens |
| 33 | Permission model | D101 guest role; §7.3 least-privilege role table |
| 36 | Sandboxed execution | ACA dynamic sessions, only if the P3b sandbox option was done |
| (option) 30, 31, 43 | Workflow integration | headless runs API, federated client authentication, CI triage and ADR review |

Phase 5 is mainly the cloud and platform work from the original brief (Terraform, Azure, identity, CI/CD); its AI
content is the quantization and model-precision checks, the cost limits of a public LLM app, and tool authentication
without stored secrets.

---

## Appendix A — Environment (additions)

```dotenv
# --- Terraform / scripts (local runs; CI uses repository variables) ---
ARM_USE_OIDC=true                         # CI only; locally: az login
ARM_TENANT_ID=…
ARM_SUBSCRIPTION_ID=…
TF_STATE_ACCOUNT=stkbtfstate…
AZ_REGION=germanywestcentral              # per ADR-0006
KB_DOMAIN=kb.example.dev

# --- api / ai-service in the cloud (set by Terraform) ---
DEMO_MODE=public
DEMO_DAILY_CAP_USD=0.30
CORS_ORIGINS=https://kb.example.dev
PUBLIC_MCP_HOST=mcp.kb.example.dev
JOBS_INPROCESS_WORKER=false
MODELS_DIR=/models
GITHUB_APP_ID=…
GITHUB_INSTALLATION_MAIN=…
GITHUB_INSTALLATION_SANDBOX=…
GITHUB_APP_KEY_ID=https://kv-kb-….vault.azure.net/keys/github-app-signing
AZURE_CLIENT_ID=…                         # id-kb-ai
OTEL_EXPORTER_OTLP_ENDPOINT=https://traces.kb.example.dev
```

## Appendix B — Command cheat sheet (additions)

```bash
pnpm az:bootstrap                            # once: state storage (local state, never committed)
pnpm az:plan -- shared|demo                  # plan with your own az login (read-only use)
gh workflow run infra-apply.yml -f stack=shared
gh workflow run deploy-demo.yml -f ref=v0.5.0
gh workflow run e2e-aks.yml -f issuer=staging
gh workflow run janitor.yml
gh workflow run demo-pause.yml -f action=pause|resume
pnpm az:models-sync                          # upload the model sets to the Files share
pnpm az:kcadm -- get realms/kb               # Keycloak admin CLI via the manual job
az containerapp logs show -n ai-service -g rg-kb-demo --follow
az containerapp job execution list -n ai-worker -g rg-kb-demo -o table
az aks get-credentials -g rg-kb-e2e -n aks-kb-e2e-<run-id>
```

## Sources checked (2026-10-24)

- Terraform release cycles (1.16.7, 22 Oct 2026) — https://endoflife.date/terraform
- azurerm provider releases (5.11.0) — https://releases.hashicorp.com/terraform-provider-azurerm/
- AzureRM 5.0 GA (28 Jul 2026, breaking changes) — https://www.hashicorp.com/blog/terraform-azurerm-provider-50-now-generally-available
- azurerm 4.x history (write-only `*_wo` arguments since 4.21/4.23) — https://learn.microsoft.com/en-us/azure/developer/terraform/provider-version-history-azurerm-4-0-0-to-current
- Terraform write-only arguments and ephemeral `random_password` — https://developer.hashicorp.com/terraform/language/manage-sensitive-data/write-only
- Container Apps pricing (free grant, idle/active, jobs) — https://azure.microsoft.com/en-us/pricing/details/container-apps/ · rates (East US): https://www.devzero.io/blog/azure-container-apps-pricing
- Container Apps workload profiles (0.25–4 vCPU, 0.5–8 GiB) — https://learn.microsoft.com/en-us/azure/container-apps/hardware
- Container Apps scaling (KEDA custom rules, cool-down 300 s) — https://learn.microsoft.com/azure/container-apps/scale-app
- Container Apps jobs (event-driven, schedule, limits) — https://learn.microsoft.com/azure/container-apps/jobs
- Container Apps cold-start guidance — https://learn.microsoft.com/azure/container-apps/cold-start
- Container Apps image architecture (amd64) — https://learn.microsoft.com/en-us/answers/questions/1485305/unable-to-deploy-images-to-azure-container-app
- Static Web Apps quotas (Free plan) — https://learn.microsoft.com/en-my/azure/static-web-apps/quotas
- Postgres Flexible B1ms price — https://www.bytebase.com/dbcost/azure-flexible/instance/B1ms/ · overview (stop ≤ 7 days, backups): https://docs.azure.cn/en-us/postgresql/flexible-server/overview · stop/start: https://docs.azure.cn/en-us/postgresql/configure-maintain/how-to-stop-server
- Container Registry tiers — https://azure.microsoft.com/en-us/pricing/details/container-registry/ · https://cloudcostkit.com/guides/azure-container-registry-pricing/
- Qdrant Cloud free tier (resources, suspension, snapshots) — https://qdrant.tech/documentation/cloud/create-cluster/ · https://www.costbench.com/software/vector-databases/qdrant/free-plan/
- AKS supported versions (1.35–1.37 GA, 1.38 GA Feb 2027) — https://learn.microsoft.com/azure/aks/supported-kubernetes-versions
- AKS app routing Gateway API GA (`approuting-istio`) — https://blog.aks.azure.com/2026/06/10/app-routing-gateway-api-ga
- Standard_D4ps_v6 prices — https://pcr.cloud-mercato.com/providers/azure/flavors/standard_d4ps_v6
- AKS-MCP releases (v0.0.20, stdio only) — https://github.com/Azure/aks-mcp/releases
- Log Analytics / Application Insights pricing — https://monitoringcost.com/azure-application-insights-pricing
- Phoenix authentication (OAuth2/OIDC, system API keys) — https://arize.com/docs/phoenix/deployment/authentication
- Phoenix hosted tier status / Arize AX Free — https://markaicode.com/pricing/arize-phoenix-pricing
- Let's Encrypt lifetimes and rate limits — https://letsencrypt.org/2026/02/24/rate-limits-45-day-certs · https://letsencrypt.org/docs/duplicate-certificate-limit
- OpenRouter per-key credit limits — https://openrouter.ai/docs/features/provisioning-api-keys
- EU AI Act Art. 50 transparency obligations (in force 2026-08-02) — https://labs.cloudsecurityalliance.org/research/csa-research-note-eu-ai-act-article-50-transparency-20260729/
