# plan-phase-4.md — Phase 4: Kubernetes

> **Parked 2026-10-26** — see [plan-daily-use.md](plan-daily-use.md).

> **Project (working title):** `kb-agent` — an assistant for the **"Dev of the future"**.
> **Document scope:** Phase 4 of 6 · **Status:** Draft v1 · **Updated:** 2026-10-24 · builds on `plan.md` v2,
> `plan-phase-2.md` v1.1, `plan-phase-3.md` v1 and `roadmap-phases-3-6.md` v1.3
> **Estimated effort:** ~46 h (range 38–60 h) · ~6 weeks at 8–10 h/week + 2 buffer weeks in summer
> **Start:** after Phase 3 (expected late June 2027) → target end late August 2027
> **Decisions taken for this plan:** Argo CD as the GitOps controller (full profile) · 16 GB Mac · workflow integration
> stays a Phase 5 option

### Review outcome (changes vs. `roadmap-phases-3-6.md` §5)

| Change | Reason |
|---|---|
| **Kick-off M4.0 (3 h) and chart CI M4.8 (3 h) added** | Five facts below need a spike first; charts need validation in CI like the code. Phase 4 grows from ~40 h to ~46 h |
| **Gateway API instead of Ingress** | Ingress NGINX was retired in March 2026; k3s 1.37 bundles the Gateway API CRDs and its Traefik 3.7 has a Gateway provider |
| **Helm 4** | Helm 3 bug fixes ended on 2026-09-09; security fixes end on 2027-02-10 |
| **No Bitnami charts or images** | Bitnami's free catalogue moved behind a subscription in 2025; the legacy images get no patches |
| **Keycloak via its Operator, Postgres via CloudNativePG** | The supported Kubernetes paths; Keycloak has documented CloudNativePG since 26.6 |
| **Models as OCI image volumes** | Stable since Kubernetes 1.36; keeps the app image small and needs no model downloads or Hugging Face tokens at runtime |
| **Read-only Kubernetes tool = `kubernetes-mcp-server`** instead of an own tool | Maintained, supports MCP 2026-07-28, has a read-only mode; same pattern as the pinned external MCP servers in P2 |
| **Egress proxy** for the hostname allow-list | Standard NetworkPolicy filters by IP, not by hostname |
| **Two resource profiles** (`k3d-lite`, `k3d-full`) | On 16 GB the full stack in k3d leaves too little for macOS and the IDE; containers on the Mac can't use the Apple GPU |
| **Public issuer vs. internal Keycloak URL** | Pods can't reach the browser-facing hostname, but tokens must keep the public issuer |
| **Argo CD** | Decision for this plan; runs in the full profile only |

---

## 0. Roadmap context

| Phase | Theme | Core hours | Result |
|---|---|---|---|
| 1 | Foundation + RAG slice + eval + tracing | ~76 | Streamed, cited answers; retrieval metrics; Phoenix traces; CI green |
| 2 | Agent | ~99 | Agent with MCP tools, approvals, conversations, audit, agent eval; taxonomy + gap signals |
| 3a | Retrieval quality, sub-topics & skills | ~75 | Hybrid + rerank + contextual + code-aware RAG, gated alias swap, priorities, skills |
| 3b | Evaluation, safety, cost, KB curator | ~76 | Judge gate, guardrails, ACL, cascade + cache, memory, compaction, curator (L2) |
| **4 (this doc)** | **Kubernetes** | **~46** | Whole stack on k3d from Helm charts, Gateway API + TLS, operators, hardening, Argo CD, read-only K8s tool, refresh CronJob (L3) |
| 5 | Azure | ~55 | Lean demo on Container Apps + SWA (~30 USD/month), ephemeral AKS via Argo CD, OIDC + managed identity, Key Vault, GitHub App; workflow integration (option) |
| 6 | MLOps, local models, polish | ~63 | Distilled CPU reranker rolled out via an MLflow alias, local-vs-API benchmark on the M1, system card, supply chain, BFF, v1.0 |

Phase 5 in detail: `plan-phase-5.md`; Phase 6: `plan-phase-6.md`.

---

## 1. Goal and demo script

**Goal.** By the end of Phase 4 the whole stack runs on a local k3d cluster from versioned Helm charts in a
production-shaped way: Gateway API with trusted TLS, Keycloak in production mode, Postgres and Keycloak managed by their
operators, models mounted as image volumes, restricted pod security, default-deny network policies with an egress
allow-list, secrets kept out of git, and Argo CD reconciling the desired state. The agent can inspect the cluster
through a read-only Kubernetes tool, and the KB refresh job (L3) runs as a CronJob. The same charts deploy to AKS in
Phase 5 with a different values file.

**Acceptance demo**

1. `pnpm k8s:up` (profile `k3d-lite`) → cluster, platform layer and apps come up; all pods in `kb` and `kb-auth` are
   Ready in under 10 minutes with cached images.
2. Open `https://kb.localhost` (trusted certificate) → login at `https://auth.kb.localhost` (Keycloak in production mode)
   → a cited answer streams; an agent turn with GitHub tools works through the egress proxy.
3. From a debug pod in `kb`: `curl https://example.com` fails, `curl https://openrouter.ai` through the proxy succeeds;
   Postgres and Qdrant are unreachable from the unlabelled debug pod.
4. Applying a privileged pod to `kb` is rejected by Pod Security Admission.
5. `kube-linter` and `kubeconform` report no findings for the rendered charts.
6. As `bob`: *"Which pods restarted in the last hour, and why?"* → `kubernetes.*` read-only tools answer (an OOMKilled
   pod with exit code 137 in the fixture scenario); asking to delete a pod → there is no write tool.
7. `pnpm k8s:refresh-now` (runs the CronJob once) → the digest lists changed sources: auto-promoted for L3 hosts, sent to
   review for the others.
8. `helm upgrade` with a new image tag in `k3d-full` → migration Job runs, api rolls without failed requests (2
   replicas, PDB).
9. Push a values change → Argo CD syncs it; the Argo CD UI shows every application healthy and in sync.
10. A PR touching `charts/` → lint, schema validation, linter and "no secrets rendered" checks; `main` → k3d smoke
    install with the `ci` profile and a Playwright smoke through the Gateway.
11. `pnpm k8s:down` → cluster gone; the Mode A dev stack from Phase 1 still works.

---

## 2. Scope

**In scope**
- k3d cluster with pinned k3s, local image registry, start/stop scripts
- Platform layer: Traefik Gateway provider, cert-manager with a local CA, CloudNativePG, Keycloak Operator
- Umbrella Helm chart for the apps, values profiles, values schema, migrations as hook Jobs
- Model images mounted as image volumes (PVC fallback)
- Hardening: probes, requests/limits, Pod Security Admission `restricted`, security contexts, default-deny network
  policies, egress proxy, HPA and PDB for stateless apps, rolling updates
- Secrets from `.env.local` with fixed names (ready for External Secrets in P5); runtime config per profile
- Argo CD app-of-apps (full profile)
- `kubernetes-mcp-server` read-only with namespace-scoped RBAC, agent eval tasks
- KB refresh CronJob (L3)
- Chart CI (lint, schema validation, linter, secret check) and a k3d smoke install on `main`; runbook

**Out of scope (deferred, with target)**
- Cloud cluster, DNS, public TLS (Let's Encrypt), Key Vault + External Secrets, workload identity, GitHub App → **5**
- Backups to object storage (CloudNativePG Barman Cloud plugin) → **5**
- Prometheus / Grafana / Loki → decided with cloud observability in **5**
- Workflow integration → **5, option**
- Image scanning and signing (Trivy), SBOMs → **6**
- Service mesh / mTLS between pods, multi-node or HA clusters → not planned

---

## 3. Decisions

Numbering continues from `plan-phase-3.md` (D75). Status: **N** = new · **C** = changes an earlier decision (named).

| # | St. | Topic | Decision | Why / alternatives |
|---|---|---|---|---|
| D76 | N | Local cluster | **k3d 5.9** with the pinned image `rancher/k3s:v1.37.1-k3s1` (Kubernetes 1.37.1, containerd 2.3, Traefik 3.7, embedded network policy controller, metrics-server, local-path provisioner). One server node, ports 80/443 mapped, local registry for dev and model images. The Docker engine VM gets ~9 GB; the Mode A dev stack is stopped while the cluster runs. (ADR-0028) | k3s bundles what this phase needs (Gateway CRDs, network policies, metrics). kind lacks a bundled gateway and policy controller; minikube is heavier; OrbStack's built-in Kubernetes is convenient but ties the setup to one tool. |
| D77 | C (D17) | Gateway, hostnames, TLS | **Gateway API** (`Gateway` + `HTTPRoute`) through k3s's Traefik Gateway provider, enabled via `HelmChartConfig`; no Ingress objects. Hostnames: `kb.localhost` (web, `/api`), `auth.kb.localhost` (Keycloak), `mcp.kb.localhost` (own MCP server). TLS ends at the Gateway with a wildcard certificate from **cert-manager 1.21** and a local CA (self-signed root → CA `ClusterIssuer`); the root is added to the macOS keychain once. Inside the cluster traffic is plain HTTP behind default-deny policies. Phoenix and Argo CD are reached via `kubectl port-forward`, not routes. SSE routes get long request timeouts and no buffering. (ADR-0029) | Ingress NGINX is retired; Gateway API is portable to AKS. mTLS inside the cluster (service mesh) costs memory and time without a demo benefit here. |
| D78 | N | Chart layering & Helm 4 | **Helm 4.3** (server-side apply by default). Two layers: **platform** (Traefik config, cert-manager, CloudNativePG, Keycloak Operator) and **apps** (umbrella chart `charts/kb-agent` with own subcharts web, api, ai-service, github-mcp, kubernetes-mcp, egress-proxy, kb-refresh; dependencies: official Qdrant chart 1.19.x, Phoenix OCI chart in the full profile). No Bitnami charts or images. Profiles: `values-k3d-lite.yaml` (default), `values-k3d-full.yaml`, `values-ci.yaml`, `values-aks.yaml` (stub for P5). Own values have a `values.schema.json`. (ADR-0030) | Operators and their CRDs change on a different rhythm than the apps; layering makes install order and upgrades explicit. |
| D79 | C (D4, D5, D36) | Keycloak on Kubernetes | **Keycloak Operator 26.8** (kustomize install, supported since 26.7) in namespace `kb-auth`; one `Keycloak` CR in production mode (`start`), database on CloudNativePG, hostname `https://auth.kb.localhost`, proxy headers `xforwarded`, HTTP inside the cluster, health on the management port. Realm bootstrap via `KeycloakRealmImport` (create-only; client secrets and URLs per profile via placeholders from Secrets). Later client changes via `KeycloakOIDCClient` CRs (preview in 26.8) if the spike works, else a dev re-import Job. **Issuer vs. internal URL:** tokens keep the public issuer; NestJS and the AI service validate `iss` against it but fetch JWKS and call the token endpoint (token exchange) through the internal Service URL (`KEYCLOAK_INTERNAL_URL`). The MCP resource URL becomes `https://mcp.kb.localhost/mcp`, so the audience mappers are set per profile. (ADR-0031) | The operator is Keycloak's supported Kubernetes path. Pods resolve `*.localhost` to themselves, so they can't use the browser-facing URL. |
| D80 | C (D15) | Postgres via CloudNativePG | **CloudNativePG 1.30** operator; one `Cluster` (1 instance, Postgres 17) with declarative `Database` resources `keycloak`, `app`, `ai` (+ `phoenix` in the full profile) and one managed role per service (the `app` role keeps INSERT/SELECT only on `audit_log`, D42). Connection Secrets come from CloudNativePG; charts reference them by name and also accept an external database (for Azure Postgres Flexible in P5). Migrations run as Helm pre-install/pre-upgrade hook Jobs (Drizzle for `app`, the `ai` schema incl. Procrastinate). Local backups: an optional nightly `pg_dump` CronJob to a PVC. (ADR-0032) | Declarative databases, roles and failover are the Kubernetes way; the external-DB switch keeps P5's managed Postgres open. |
| D81 | N | Model artifacts | Models ship as **OCI image volumes** (stable since 1.36): one `FROM scratch` image per model set (`models-embed`, `models-rerank`, `models-guard`, `models-docling`, `models-spacy`), mounted read-only into the AI service; the app image carries code only. Gated or non-commercial models (Prompt Guard, the jina reranker) live only in the local registry (in P5 on a private Azure Files share, plan-phase-5 D94), never in public GHCR. Fallback if k3s's containerd can't mount image volumes: a `models` PVC filled by an init Job. (ADR-0033) | No runtime downloads, no Hugging Face token in the cluster, independent model versions. |
| D82 | C (D50, D53) | Resource profiles | **`k3d-lite` (default):** AI service limit ~4 GB with a CPU-friendly reranker (D57's ONNX candidate or MiniLM) and Prompt Guard 22M, Phoenix and Argo CD off, worker in-process (one copy of the models). **`k3d-full`:** everything incl. Phoenix and Argo CD, api with 2 replicas, for demos with the IDE closed. Requests from measured usage (`kubectl top`), limits ≈ 1.3× peak; Keycloak with container-aware JVM heap. ai-service: startup probe for model loading, 1 replica; HPA only for web and api (CPU 70 %); PDB where replicas ≥ 2. A separate worker Deployment (`ai.worker.separate: true`) is tested once in `k3d-full` and becomes the default on AKS. | Containers on the Mac have no Apple GPU (MPS), so D57's MPS reranker runs on CPU here. |
| D83 | N | Pod security & network policy | Namespaces `kb` (apps, CloudNativePG cluster, Qdrant) and `kb-auth` (Keycloak Operator + Keycloak) enforce Pod Security Admission **`restricted`**: non-root, read-only root file system (emptyDir for `/tmp` and caches), all capabilities dropped, seccomp `RuntimeDefault`, no service-account token unless needed. **Default-deny** ingress and egress in both namespaces, explicit allows per flow (§7.5), DNS allowed. **Egress:** only the egress-proxy pod (Squid, CONNECT on 443, domain allow-list from values incl. the curator hosts) may reach the internet; apps use `HTTPS_PROXY`. (ADR-0034) | NetworkPolicy can't match hostnames; a proxy enforces the allow-list and works the same on AKS. Cilium FQDN policies were considered but are heavier on k3d. |
| D84 | C (D26) | Secrets & runtime config | No secret values in charts or git. `scripts/k8s/secrets.sh` creates Secrets from `.env.local` with fixed names (§7.4); charts reference names only, so External Secrets Operator (2.13) can create the same Secrets from Key Vault in P5. Runtime config via ConfigMaps from values; web `config.json` per profile. Argo CD never manages Secrets in P4. | One secret contract for local and cloud. |
| D85 | N | GitOps with Argo CD | **Argo CD 3.5** (non-HA manifest) in namespace `argocd`, full profile only. App-of-apps with sync waves: platform → data → auth → apps; Helm values per profile; auto-sync with self-heal on k3d; `ignoreDifferences` for operator-managed fields; Secrets excluded (pre-created). Source: the GitHub repo, branch `main`. (ADR-0035) | UI for demos and the most common controller in job postings; memory paid only in the full profile. |
| D86 | N | Read-only Kubernetes tool | **`containers/kubernetes-mcp-server`** (pinned 0.0.6x; supports MCP 2026-07-28; Streamable HTTP) in `kb`, read-only, toolset allow-list (pods, logs, events, deployments, rollout status). ServiceAccount bound to a namespace-scoped Role (get/list/watch on pods, pods/log, events, deployments, replicasets, statefulsets, jobs; no Secrets). Registered in `mcp_servers.yaml` (domain `sre`, min role editor); outputs pass the guardrails (secrets in logs, D69). Agent eval with a fixture server and scenario. Own tool only as fallback. (ADR-0036) | Reuses a maintained server; the learning is in RBAC and least privilege. |
| D87 | N | KB refresh CronJob (L3) | Weekly `CronJob` (`concurrencyPolicy: Forbid`) with a small client image calling `POST /v1/curator/refresh` using client credentials (`kb-refresh`, role `curator-refresh`); the work runs in the AI service worker, where the models are. Conditional GET (ETag / Last-Modified) + content hash; a changed page → new staged version → promotion eval → auto-promote only if every gate passes **and** the host has `l3: true` in `sources.yaml`, otherwise the review queue. `l3: true` is accepted only when the roadmap §8.1 rule holds (≥ 20 reviewed proposals, ≥ 90 % accepted, no incident). Weekly digest in the admin page; kill switch `refresh.enabled`. | The CronJob only triggers; models and gates stay in one place. |
| D88 | C (D19) | Chart CI | PRs touching `charts/` or `infra/k8s/`: `helm lint`, `helm template` per profile → `kubeconform` (incl. CRD schemas), `kube-linter`, and a check that no secret values are rendered. On `main`: k3d smoke install with `values-ci.yaml` (amd64 runner, `LLM_PROVIDER=fake`, e5-small model image, fixture corpus) → wait for Ready → Playwright smoke through the Gateway. | Infrastructure changes get the same gate as code. |

---

## 4. Assumptions and open items

| # | Assumption | If wrong |
|---|---|---|
| A21 | Phase 3 is done; deviations recorded in `plan-phase-3.md` before M4.0 | Shift the schedule |
| A22 | The Docker engine VM can get ~9 GB on the 16 GB Mac while macOS, browser and a light editor keep running | `k3d-lite` only, Phoenix and Argo CD never together, IDE closed for demos |
| A23 | containerd 2.3 in k3s 1.37 mounts image volumes | `models` PVC filled by an init Job |
| A24 | Keycloak's hostname options let backends use the internal URL while `iss` stays public | CoreDNS rewrite so `auth.kb.localhost` resolves to the Traefik Service inside the cluster |
| A25 | `kubernetes-mcp-server` read-only mode works with the MCP SDK v2 client | Own read-only tool with the Kubernetes Python client (~2 h more) |
| A26 | The Phoenix chart can use an external Postgres (CloudNativePG `phoenix` database) | Phoenix with its chart's own small database, full profile only |
| A27 | Standard GitHub-hosted runners can run the `ci` profile on k3d | Smoke install on a schedule only, or a reduced chart subset |

**Still open (decided inside the milestones):** Squid vs. tinyproxy for the egress proxy (M4.3), `KeycloakOIDCClient` vs.
re-import Job (M4.0/M4.1), exact request/limit values (M4.3), Argo CD sync policy for the CloudNativePG cluster (M4.5),
the `ci` profile's fixture corpus (M4.8).

---

## 5. Architecture (Phase 4)

```
 macOS (16 GB) ── Docker engine VM (~9 GB) ── k3d cluster "kb" (k3s v1.37.1, 1 server node)
   browser ─► https://kb.localhost · https://auth.kb.localhost · https://mcp.kb.localhost   (ports 80/443)
   ┌────────────────────────────────────────────────────────────────────────────────────────────────┐
   │ kube-system   Traefik 3.7 (Gateway provider) · Gateway `kb` (TLS) · CoreDNS · metrics-server   │
   │ cert-manager  local CA ClusterIssuer → wildcard certificate *.kb.localhost                       │
   │ cnpg-system   CloudNativePG operator                                                             │
   │ argocd        Argo CD (full profile): app-of-apps → platform → data → auth → apps                │
   │ kb-auth       Keycloak Operator · Keycloak (production mode)            [PSA restricted, deny]   │
   │ kb            web (nginx) · api (NestJS, HPA) · ai-service (+ in-process worker, model volumes)   │
   │               github-mcp · kubernetes-mcp (read-only SA) · qdrant (StatefulSet + PVC)             │
   │               postgres (CNPG Cluster: keycloak, app, ai[, phoenix]) · phoenix (full profile)       │
   │               egress-proxy (only pod with internet egress) · kb-refresh (CronJob)                 │
   │                                                                     [PSA restricted, deny]   │
   └────────────────────────────────────────────────────────────────────────────────────────────────┘
   k3d registry: dev app images + model images (never pushed to public registries)
   internet (via egress-proxy only): OpenRouter · GitHub API · Azure · curator hosts
```

| Component | Change in Phase 4 |
|---|---|
| web, api, ai-service, github-mcp | Run as Deployments from the umbrella chart; config from values; secrets by name |
| ai-service | Models from image volumes; `KEYCLOAK_INTERNAL_URL`; `HTTPS_PROXY`; worker in-process (lite) or separate (full, AKS) |
| Keycloak | Operator-managed, production mode, realm import with placeholders |
| Postgres | CloudNativePG `Cluster` + `Database` resources; external-DB switch for P5 |
| Qdrant | Official chart, StatefulSet with PVC, API key from a Secret |
| New | Egress proxy, `kubernetes-mcp-server`, `kb-refresh` CronJob, Argo CD (full) |

**Request path:** browser → Gateway (TLS) → HTTPRoute → Service → pod. SSE from `/api/conversations/:id/messages` passes
Traefik unbuffered with a request timeout above the agent's 120 s run limit (D27).

**Token path:** the browser gets tokens from `https://auth.kb.localhost` (issuer = public URL); NestJS and the AI service
check that issuer, but load JWKS and run token exchange against `http://keycloak-service.kb-auth:8080`.

**Egress path:** ai-service and github-mcp → `egress-proxy:3128` → allow-listed host; every other destination outside
the cluster is dropped by the network policies.

**Install order:** cluster → platform (Traefik config, cert-manager, CloudNativePG, Keycloak Operator) → data (CNPG
`Cluster`, Qdrant) → auth (`Keycloak`, realm import) → secrets script → apps (migrations hook first). Argo CD reproduces
the same order with sync waves.

---

## 6. Repository layout (additions)

```
kb-agent/
├─ charts/kb-agent/                  # umbrella chart (apps)
│  ├─ Chart.yaml                     # deps: qdrant (official), phoenix (OCI, full profile)
│  ├─ values.yaml · values.schema.json
│  ├─ values-k3d-lite.yaml · values-k3d-full.yaml · values-ci.yaml · values-aks.yaml (stub)
│  └─ charts/{web,api,ai-service,github-mcp,kubernetes-mcp,egress-proxy,kb-refresh}/
├─ infra/k8s/
│  ├─ versions.env                   # pinned k3d, k3s, Helm, operators, charts
│  ├─ k3d/cluster.yaml               # k3s image, ports, registry, Traefik HelmChartConfig
│  ├─ platform/                      # cert-manager issuers + wildcard Certificate, Gateway `kb`
│  ├─ data/                          # CNPG Cluster + Database CRs, managed roles
│  ├─ auth/                          # Keycloak CR, KeycloakRealmImport, KeycloakOIDCClient (if adopted)
│  ├─ policies/                      # namespace labels (PSA), NetworkPolicies, RBAC for kubernetes-mcp
│  └─ argocd/                        # app-of-apps with sync waves
├─ images/models/                    # one Dockerfile (FROM scratch) per model set
├─ scripts/k8s/{up.sh,down.sh,secrets.sh,build-images.sh,trust-ca.sh,refresh-now.sh,prune.sh}
└─ docs/runbooks/k8s.md              # upgrade, rollback, reset, common failures
```

---

## 7. Contracts (draft — rendered manifests and the values schema are authoritative)

### 7.1 Hostnames and routes

| Host | Path | Backend | Notes |
|---|---|---|---|
| `kb.localhost` | `/` | web (nginx, `config.json` per profile) | HTTP → HTTPS redirect on the Gateway |
| `kb.localhost` | `/api` | api :3000 | SSE: request timeout > 120 s, no buffering |
| `auth.kb.localhost` | `/` | Keycloak :8080 (`kb-auth`) | admin console on the same host (Keycloak admin login); restricted in P5 |
| `mcp.kb.localhost` | `/mcp`, `/.well-known/oauth-protected-resource/mcp` | ai-service :8000 | resource URL `https://mcp.kb.localhost/mcp` |
| — | — | Phoenix, Argo CD UI | `kubectl port-forward` only |

### 7.2 Values (excerpt of `values-k3d-lite.yaml`)

```yaml
global:
  domain: kb.localhost
  keycloak: {issuer: https://auth.kb.localhost/realms/kb, internalUrl: http://keycloak-service.kb-auth:8080}
  egressProxy: {url: http://egress-proxy:3128, noProxy: ".svc,.cluster.local,localhost,127.0.0.1"}
  database: {mode: cnpg, cluster: kb-pg}            # or: external (P5) with secretRef
api:        {replicas: 1, resources: {requests: {cpu: 100m, memory: 256Mi}, limits: {memory: 384Mi}}}
aiService:
  worker: {separate: false}                       # true in k3d-full test and on AKS
  models:
    source: imageVolume                           # or: pvc (fallback)
    images: {embed: k3d-registry.localhost:5001/models-embed:bge-m3-1,
             rerank: k3d-registry.localhost:5001/models-rerank:cpu-1,
             guard:  k3d-registry.localhost:5001/models-guard:pg2-22m-1}
  resources: {requests: {cpu: 500m, memory: 3Gi}, limits: {memory: 4Gi}}
phoenix: {enabled: false}
argocd:  {enabled: false}
refresh: {enabled: true, schedule: "0 6 * * 1"}
```
All numbers are starting values; M4.3 replaces them with measured ones.

### 7.3 Environment changes

| Variable | Service | Value in k3d |
|---|---|---|
| `KEYCLOAK_ISSUER` / `AI_KEYCLOAK_ISSUER` | api / ai-service | `https://auth.kb.localhost/realms/kb` (checked against `iss`) |
| `KEYCLOAK_INTERNAL_URL` (new) | api, ai-service, kb-refresh | `http://keycloak-service.kb-auth:8080` (JWKS, token endpoint) |
| `MCP_RESOURCE_URL` | ai-service | `https://mcp.kb.localhost/mcp` |
| `HTTPS_PROXY`, `NO_PROXY` (new) | ai-service, github-mcp | proxy URL; cluster-internal names excluded |
| `MODELS_DIR` (new) | ai-service | `/models` (image-volume mounts per model set) |
| `JOBS_INPROCESS_WORKER` | ai-service | `true` (lite) / `false` (separate worker) |

### 7.4 Secret names (contract for External Secrets in P5)

| Secret | Keys | Used by |
|---|---|---|
| `kb-openrouter` | `api-key` | ai-service |
| `kb-keycloak-clients` | `kb-api`, `kb-ai`, `kb-refresh` client secrets | api, ai-service, kb-refresh, realm import placeholders |
| `kb-approval-signing` | `hmac-key` | ai-service |
| `kb-github-read` · `kb-github-sandbox` | `token` | github-mcp · ai-service (sandbox write) |
| `kb-azure-sp` | `tenant-id`, `client-id`, `client-secret`, `subscription-id` | ai-service (Azure MCP) |
| `kb-qdrant` | `api-key` | ai-service, qdrant |
| `kb-pg-*` (CloudNativePG-generated) | `uri`, `username`, `password` | api, ai-service, Keycloak |

### 7.5 Network policy matrix (namespaces `kb`, `kb-auth`; default-deny both directions)

| From | To | Port |
|---|---|---|
| Traefik (`kube-system`) | web 8080 · api 3000 · ai-service 8000 (`/mcp`) · Keycloak 8080 | TCP |
| api | ai-service 8000 · postgres 5432 · Keycloak 8080 | TCP |
| ai-service | postgres 5432 · qdrant 6333/6334 · Keycloak 8080 · github-mcp 8082 · kubernetes-mcp 8080 · phoenix 4317 · egress-proxy 3128 | TCP |
| Keycloak | postgres 5432 | TCP |
| github-mcp | egress-proxy 3128 | TCP |
| kubernetes-mcp | Kubernetes API server | 6443 |
| kb-refresh | Keycloak 8080 · ai-service 8000 | TCP |
| CloudNativePG operator (`cnpg-system`) | postgres pods 8000 / 5432 | TCP |
| egress-proxy | `0.0.0.0/0` except cluster CIDRs | 443 |
| every pod | kube-dns 53 | UDP/TCP |

### 7.6 RBAC for `kubernetes-mcp` (namespace `kb`)

```yaml
kind: Role
rules:
  - apiGroups: [""]
    resources: [pods, pods/log, events, services, endpoints, configmaps]
    verbs: [get, list, watch]
  - apiGroups: [apps, batch]
    resources: [deployments, replicasets, statefulsets, jobs, cronjobs]
    verbs: [get, list, watch]
# no secrets, no exec, no write verbs; bound to ServiceAccount kubernetes-mcp only
```

### 7.7 `mcp_servers.yaml` addition

```yaml
  kubernetes:
    transport: http
    url: http://kubernetes-mcp.kb:8080/mcp        # in-cluster; read-only mode, toolset allow-list
    auth: none                                     # reachable only from ai-service (network policy)
    allow: [ … from the pinned tools/list … ]
    domains: [sre, devops]
    min_role: editor
```

### 7.8 Model image and mount

```dockerfile
# images/models/embed/Dockerfile
FROM scratch
COPY bge-m3/ /bge-m3/
```

```yaml
volumes:
  - name: models-embed
    image: {reference: k3d-registry.localhost:5001/models-embed:bge-m3-1, pullPolicy: IfNotPresent}
containers:
  - name: ai-service
    volumeMounts: [{name: models-embed, mountPath: /models/embed, readOnly: true}]
```

### 7.9 SRE agent task (`evals/datasets/agent_v2.jsonl`, fixture scenario)

```json
{"id":"a-061","lang":"en","domains":["sre"],"type":"tool-selection","scenario":"k8s-oomkilled-ai-service",
 "prompt":"Which pods restarted in the last hour, and why?",
 "expect":{"tools_required":["kubernetes.<pods-list-tool>"],"tools_forbidden":["github_sandbox.create_issue"],
           "answer_regex":["(?i)oomkilled|137"],"max_steps":5}}
```

---

## 8. Milestones and tasks

Order: M4.0 → M4.1 → M4.2 → M4.3 → M4.4 → M4.5 → M4.6 → M4.7 → M4.8. Hours are ideal single-person hours, ±30 %.

### M4.0 — Kick-off & spikes (~3 h)

- [ ] Record Phase 3 deviations; measure the Mode A stack as the memory baseline
- [ ] **Spikes (≤ 30 min each):** image volume with a 2 GB model image on k3s 1.37.1 · Keycloak in production mode
  behind Traefik with public `iss` and internal backchannel from a pod · Phoenix chart with an external Postgres ·
  `kubernetes-mcp-server` read-only with the SDK v2 client · Traefik Gateway provider + cert-manager Gateway support +
  SSE through the Gateway
- [ ] Pin k3d 5.9, k3s v1.37.1+k3s1, Helm 4.3, cert-manager 1.21, CloudNativePG 1.30, Keycloak Operator 26.8, Qdrant chart
  1.19.x, Argo CD 3.5, kubernetes-mcp-server in `infra/k8s/versions.env`

**Acceptance:** spike results in the ADR-0028 … 0033 drafts; versions pinned.

### M4.1 — Cluster & platform layer (~9 h)

- [ ] `infra/k8s/k3d/cluster.yaml` (1 server, ports 80/443, registry, pinned k3s image); `pnpm k8s:up` / `k8s:down`
- [ ] Traefik `HelmChartConfig` with the Gateway provider; Gateway `kb` (HTTPS, HTTP → HTTPS redirect)
- [ ] cert-manager with Gateway support; self-signed root → CA `ClusterIssuer` → wildcard certificate;
  `scripts/k8s/trust-ca.sh` adds the root to the macOS keychain (and documents `NODE_EXTRA_CA_CERTS` for Node-based
  MCP clients)
- [ ] CloudNativePG operator, `Cluster`, `Database` resources, managed roles, connection Secrets
- [ ] Keycloak Operator (kustomize), `Keycloak` CR (D79), `KeycloakRealmImport` with placeholders; `KeycloakOIDCClient`
  or re-import Job per the spike; HTTPRoute for `auth.kb.localhost`

**Acceptance:** `https://auth.kb.localhost` shows the login with a trusted certificate; realm `kb` with seed users;
the CloudNativePG cluster is healthy with all databases.

### M4.2 — App chart, model images, migrations (~12 h)

- [ ] Umbrella chart and subcharts; official Qdrant chart (PVC, API key); Phoenix OCI chart (full profile, external DB)
- [ ] Values profiles and `values.schema.json`
- [ ] Model images (`images/models/*`) built and pushed to the k3d registry; image-volume mounts; PVC fallback behind
  a flag
- [ ] Migration hook Jobs (Drizzle `app`; `ai` schema incl. Procrastinate)
- [ ] Issuer / internal-URL split in NestJS and the AI service; per-profile audience mapper values; MCP resource URL
- [ ] HTTPRoutes for `kb.localhost` and `mcp.kb.localhost`; SSE relay test through the Gateway
- [ ] Separate-worker switch tested once in `k3d-full`
- [ ] `scripts/k8s/build-images.sh` (arm64 dev builds to the registry; tags = git SHA, never `latest`)

**Acceptance:** demo steps 1–2; a re-index job, an agent turn and an MCP Inspector check work in the cluster.

### M4.3 — Hardening (~6 h)

- [ ] Probes (startup probe for the AI service), requests/limits from `kubectl top`, JVM settings for Keycloak
- [ ] PSA `restricted` on `kb` and `kb-auth`; security contexts; read-only root file systems with emptyDirs;
  service-account tokens only where needed; overrides for third-party images (Qdrant, Phoenix, proxy) documented
- [ ] Default-deny NetworkPolicies and the allow matrix (§7.5)
- [ ] Egress proxy (CONNECT 443 only, allow-list from values incl. curator hosts); `HTTPS_PROXY` / `NO_PROXY` wired;
  every external call path tested (OpenRouter, GitHub MCP, Azure MCP, curator fetch, OpenRouter web search)
- [ ] HPA for web and api; PDB and `maxUnavailable: 0` for api in `k3d-full`
- [ ] Scripted checks: unlabelled debug pod can't reach Postgres/Qdrant; non-allow-listed egress fails; privileged pod
  rejected

**Acceptance:** demo steps 3–5 and 8; `kube-linter` clean; ADR-0034.

### M4.4 — Secrets & runtime config (~2 h)

- [ ] `scripts/k8s/secrets.sh` (idempotent, fixed names §7.4); charts reference names only
- [ ] ConfigMaps from values; web `config.json` per profile; ESO mapping notes for P5

**Acceptance:** a fresh cluster comes up from `.env.local` alone; rendered manifests contain no secret values (CI check).

### M4.5 — Argo CD (~3 h)

- [ ] Argo CD 3.5 (non-HA) in the full profile; app-of-apps with sync waves (platform → data → auth → apps)
- [ ] Per-profile values; auto-sync with self-heal; `ignoreDifferences` for operator-managed fields; Secrets excluded
- [ ] ADR-0035; README screenshot of the healthy app tree

**Acceptance:** demo step 9.

### M4.6 — Read-only Kubernetes tool (~4 h)

- [ ] `kubernetes-mcp-server` Deployment (read-only, Streamable HTTP, toolset allow-list), ServiceAccount + Role (§7.6)
- [ ] `mcp_servers.yaml` entry; guardrails on its outputs
- [ ] Fixture server + scenario (OOMKilled AI-service pod, CrashLoopBackOff); ~6 SRE tasks in `agent_v2`; schema
  contract test against the pinned server
- [ ] ADR-0036

**Acceptance:** demo step 6; no write tool in `tools/list`; `kubectl auth can-i get secrets --as …` → no.

### M4.7 — KB refresh CronJob (L3) (~4 h)

- [ ] `POST /v1/curator/refresh` (service role) → refresh job: conditional GET, hash, staged version, promotion eval,
  auto-promote rule, review queue
- [ ] `sources.yaml` field `l3`; the trust rule (roadmap §8.1) checked before `l3: true` is accepted
- [ ] CronJob (weekly, `Forbid`, client credentials `kb-refresh`), kill switch, weekly digest in the admin page

**Acceptance:** demo step 7; a gate failure blocks auto-promotion (test); a non-L3 host always goes to review.

### M4.8 — Chart CI, smoke install, docs (~3 h)

- [ ] PR checks: `helm lint`, `kubeconform` with CRD schemas, `kube-linter`, "no secrets rendered"
- [ ] `main`: k3d smoke install with `values-ci.yaml` → Ready → Playwright smoke through the Gateway
- [ ] README Kubernetes section (diagram, profiles, `pnpm k8s:up`, trusting the CA); `docs/runbooks/k8s.md`

**Acceptance:** demo steps 10–11; a stranger reaches demo steps 1–2 from the README.

---

## 9. Schedule (8–10 h/week, 9 h used)

| Week | Focus |
|---|---|
| 1 | M4.0 kick-off, start M4.1 |
| 2 | M4.1 platform layer, start M4.2 |
| 3 | M4.2 app chart, model images, migrations |
| 4 | M4.3 hardening, M4.4 secrets, M4.5 Argo CD |
| 5 | M4.6 Kubernetes tool, M4.7 refresh CronJob |
| 6 | M4.8 CI and docs → exit demo |
| — | **2 buffer weeks** (summer) |

**Cut line** (drop in this order): Phoenix in the cluster → separate-worker test → Playwright step of the CI smoke (keep
the install smoke) → Argo CD self-heal (manual sync) → HPA (fixed replicas) → `KeycloakOIDCClient` (re-import Job) →
`pg_dump` CronJob.
**Never cut:** pinned versions, Gateway with trusted TLS, Keycloak in production mode with the issuer/internal split,
PSA `restricted`, default-deny network policies, egress proxy, no secrets in git, model image volumes (or the PVC
fallback), chart lint and schema validation in CI, read-only Kubernetes tool with RBAC, refresh gates.

---

## 10. Definition of Done (Phase 4)

- [ ] Demo script (§1) passes on a fresh clone with `k3d-lite` on the 16 GB Mac
- [ ] All versions pinned in `infra/k8s/versions.env`; no Bitnami artefacts; no `latest` tags
- [ ] TLS trusted in the browser; Keycloak in production mode; tokens validated against the public issuer
- [ ] PSA `restricted` enforced; default-deny network policies; internet egress only through the proxy
- [ ] Rendered manifests contain no secrets; Secrets created from `.env.local` with the §7.4 names
- [ ] Models mounted as image volumes (or the documented PVC fallback); app image without model files
- [ ] Argo CD reconciles the full profile from the repo
- [ ] Read-only Kubernetes tool with namespace-scoped RBAC; SRE tasks in the agent eval
- [ ] Refresh CronJob promotes only through the gates and only for L3 hosts
- [ ] Chart CI and the k3d smoke install green
- [ ] ADR-0028 … 0036 written; README and `docs/runbooks/k8s.md` updated

---

## 11. Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Stack doesn't fit the 16 GB Mac | Medium–High | `k3d-lite`, Mode A stopped, Phoenix/Argo CD only in `k3d-full`, measured requests |
| Image volumes not supported by the bundled containerd | Medium | Spike in M4.0; PVC fallback behind a flag |
| Issuer / backchannel misconfiguration (login works, backend token checks fail) | Medium–High | Spike in M4.0; token test matrix run inside the cluster; CoreDNS rewrite as fallback |
| SSE buffered or cut by the Gateway | Medium | Route timeouts and buffering set explicitly; relay test through the Gateway in M4.2 |
| Third-party images break under PSA `restricted` | Medium | Security-context overrides; documented exceptions only where unavoidable |
| HTTP clients that ignore `HTTPS_PROXY` | Medium | Test each external path in M4.3; explicit proxy config where an SDK needs it |
| Operator upgrades change CRDs or behaviour | Medium | Pinned versions; upgrade steps in the runbook; Argo CD sync waves |
| Argo CD fights operator-managed fields or Helm hooks | Medium | `ignoreDifferences`, hooks mapped to sync hooks, sync waves |
| Licensed model weights pushed to a public registry by mistake | Low–Medium | Model images only in the local registry (private Azure Files share in P5); CI pushes no model images except e5-small |
| Disk usage on the Mac (images, registry, PVCs) | Medium | `scripts/k8s/prune.sh`; model images shared between cluster rebuilds |
| Kubernetes rabbit holes eat the AI time | Medium | Time-boxed spikes, cut line, two buffer weeks |

---

## 12. Hand-off to Phase 5

- Same charts with `values-aks.yaml`: external Postgres (Azure Postgres Flexible) via the D80 switch, separate worker
  Deployment, replicas and HPA for real nodes
- Gateway API carries over; choose the AKS Gateway implementation and add Let's Encrypt to cert-manager
- External Secrets Operator + Key Vault create the §7.4 Secrets; workload identity and a GitHub App replace PATs and the
  service-principal secret
- Model sets → a private Azure Files share (Container Apps mount; AKS uses the PVC path); image volumes stay the k3d
  path; a private ACR only as a fallback flag (plan-phase-5 D94)
- Refresh CronJob → also a scheduled Container Apps job in the lean always-on demo
- Argo CD bootstraps the ephemeral AKS cluster from the repo
- Cloud observability decision (Phoenix in-cluster vs. Azure Monitor) replaces the port-forward setup (decided in
  plan-phase-5 D98: Phoenix on Container Apps for both environments)
- Workflow integration option needs the public MCP and API endpoints that P5 creates

---

## 13. Study-list coverage in Phase 4

| # | Topic | Where in Phase 4 |
|---|---|---|
| 8, 43 | Idempotent ingestion, eval as gate | D87 refresh with promotion gates (L3) |
| 19 | Data privacy | D83 egress allow-list; D81 licensed models kept private |
| 20 | Prompt injection | D86 Kubernetes tool outputs pass the guardrails |
| 30 | MCP | D86 external MCP server in-cluster; MCP resource URL over HTTPS |
| 31, 33 | Least privilege, permission model | D86 namespace-scoped read-only RBAC; D83 pod security |
| 42 | Agent evaluation | M4.6 SRE tasks with a fixture scenario |

Phase 4 is mainly the platform work from the original brief (Docker, Kubernetes, CI/CD); its AI content is the tool,
the refresh gates and the security boundaries around them.

---

## Appendix A — Environment and values (additions)

```dotenv
# --- local cluster (scripts/k8s) ---
K3D_CLUSTER=kb
K3D_REGISTRY=k3d-registry.localhost:5001
K8S_PROFILE=k3d-lite                       # k3d-lite | k3d-full | ci
K8S_DOMAIN=kb.localhost

# --- api / ai-service (rendered by the chart) ---
KEYCLOAK_INTERNAL_URL=http://keycloak-service.kb-auth:8080
HTTPS_PROXY=http://egress-proxy:3128
NO_PROXY=.svc,.cluster.local,localhost,127.0.0.1
MODELS_DIR=/models
MCP_RESOURCE_URL=https://mcp.kb.localhost/mcp
```

## Appendix B — Command cheat sheet (additions)

```bash
pnpm k8s:up [--profile k3d-full]           # cluster + platform + secrets + apps
pnpm k8s:down                              # delete the cluster (registry and model images kept)
pnpm k8s:images                            # build app + model images, push to the k3d registry
pnpm k8s:trust-ca                          # add the local root CA to the macOS keychain
pnpm k8s:secrets                           # create/update Secrets from .env.local
pnpm k8s:refresh-now                       # run the kb-refresh CronJob once
pnpm k8s:check                             # helm lint, kubeconform, kube-linter, secret check
pnpm k8s:prune                             # remove unused images and volumes
kubectl -n argocd port-forward svc/argocd-server 8443:443
kubectl -n kb port-forward svc/phoenix 6006:6006
```

## Sources checked (2026-10-24)

- K3s 1.37 release (Kubernetes 1.37, Traefik 3.7.13, bundled Gateway API CRDs) — https://docs.k3s.io/blog/2026/09/10/K3s-1.37-release · release notes (v1.37.1+k3s1, containerd 2.3.4): https://docs.k3s.io/release-notes/v1.37.X
- K3s networking (embedded network policy controller, Traefik Gateway provider) — https://docs.k3s.io/networking/networking-services
- k3d releases (5.9.0) — https://github.com/k3d-io/k3d/releases
- Kubernetes 1.37 release page — https://kubernetes.io/releases/1.37/
- KEP-4639 image volumes (stable in 1.36) — https://www.kubernetes.dev/resources/keps/4639/
- Helm 3 end of life / Helm 4 — https://helm.sh/blog/helm-v3-end-of-life
- Ingress NGINX retirement statement — https://www.kubernetes.io/blog/2026/01/29/ingress-nginx-statement/
- cert-manager releases (1.21.2, Gateway API settings) — https://releasebot.io/updates/cert-manager
- CloudNativePG API v1.30.0 — https://pkg.go.dev/github.com/cloudnative-pg/api@v1.30.0
- Keycloak release notes (Operator install, KeycloakOIDCClient preview, CloudNativePG guide) — https://www.keycloak.org/docs/latest/release_notes/index.html
- Keycloak realm import behaviour (create-only, placeholders) — https://docs.redhat.com/en/documentation/red_hat_build_of_keycloak/26.4/html/operator_guide/realm-import-
- Bitnami catalogue changes — https://www.docker.com/blog/broadcoms-new-bitnami-restrictions-migrate-easily-with-docker/
- Phoenix Helm deployment — https://arize.com/docs/phoenix/self-hosting/deployment-options/kubernetes-helm
- Argo CD releases (3.5.2) — https://github.com/argoproj/argo-cd/releases
- Argo CD vs. Flux in 2026 — https://lucaberton.com/blog/argocd-vs-flux-2026/
- External Secrets Operator 2.13 — https://endoflife.ai/external-secrets/2.13
- kubernetes-mcp-server releases (MCP 2026-07-28 support) — https://github.com/containers/kubernetes-mcp-server/releases · overview: https://mcp.directory/blog/kubernetes-mcp-server-complete-guide-2026
