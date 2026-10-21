import {
  BadGatewayException,
  GatewayTimeoutException,
  HttpException,
  Inject,
  Injectable,
} from '@nestjs/common';
import type { components } from '@fs100/contracts/ai-service';
import { CONFIG, type Config } from '../config.js';

type Schemas = components['schemas'];
export type ChatRequest = Schemas['ChatRequest'];
export type AgentRequest = Schemas['AgentRequest'];
export type Labels = Schemas['Labels'];
export type SearchRequest = Schemas['SearchRequest'];
export type SearchResponse = Schemas['SearchResponse'];
export type IngestResult = Schemas['IngestResult'];
export type ServiceStatus = Schemas['ServiceStatus'];
export type Domain = NonNullable<SearchRequest['domains']>[number];

/** Calls the internal AI service with the API's client-credentials token (`aud=kb-ai`, D5). */
@Injectable()
export class AiClient {
  private token?: { value: string; expiresAt: number };

  constructor(@Inject(CONFIG) private readonly config: Config) {}

  async get<T>(path: string, requestId: string): Promise<T> {
    const res = await this.request(path, requestId, { signal: AbortSignal.timeout(5_000) });
    return (await res.json()) as T;
  }

  async search(body: SearchRequest, requestId: string): Promise<SearchResponse> {
    const res = await this.request('/v1/search', requestId, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(30_000),
    });
    return (await res.json()) as SearchResponse;
  }

  async ingest(form: FormData, requestId: string): Promise<IngestResult> {
    const res = await this.request('/v1/ingest', requestId, {
      method: 'POST',
      body: form,
      // Embedding a 20 MB PDF on CPU takes minutes; without a cap a hung call keeps the row busy.
      signal: AbortSignal.timeout(15 * 60_000),
    });
    return (await res.json()) as IngestResult;
  }

  async updateLabels(docId: string, labels: Labels, requestId: string): Promise<void> {
    await this.request(`/v1/documents/${docId}/labels`, requestId, {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(labels),
      signal: AbortSignal.timeout(30_000),
    });
  }

  async deleteDocument(docId: string, requestId: string): Promise<void> {
    await this.request(`/v1/documents/${docId}`, requestId, {
      method: 'DELETE',
      signal: AbortSignal.timeout(30_000),
    });
  }

  /** Opens the SSE stream; aborting `signal` closes the connection, which cancels the LLM call. */
  chat(body: ChatRequest, requestId: string, signal: AbortSignal): Promise<Response> {
    return this.request('/v1/chat', requestId, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    });
  }

  /** SSE v2 (plan-phase-2 §7.3); aborting `signal` cancels the run like `chat`. */
  agent(body: AgentRequest, requestId: string, signal: AbortSignal): Promise<Response> {
    return this.request('/v1/agent', requestId, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    });
  }

  /** Non-2xx: client errors keep their status and detail, everything else becomes a 502/504. */
  private async request(
    path: string,
    requestId: string,
    init: Omit<RequestInit, 'headers'> & { headers?: Record<string, string> },
  ): Promise<Response> {
    const res = await fetch(new URL(path, this.config.AI_SERVICE_URL), {
      ...init,
      headers: {
        ...init.headers,
        authorization: `Bearer ${await this.serviceToken()}`,
        'x-request-id': requestId,
      },
    }).catch((error: unknown) => {
      if (error instanceof Error && error.name === 'TimeoutError') {
        throw new GatewayTimeoutException(`AI service ${path} timed out`);
      }
      throw new BadGatewayException(`AI service unreachable: ${String(error)}`);
    });
    if (res.ok) return res;
    if (res.status < 500 && res.status !== 401 && res.status !== 403) {
      throw new HttpException(await detailOf(res), res.status);
    }
    throw new BadGatewayException(`AI service ${path}: HTTP ${res.status}`);
  }

  private async serviceToken(): Promise<string> {
    // Renew 30 s early so a token never expires in flight.
    if (this.token && this.token.expiresAt - 30_000 > Date.now()) return this.token.value;

    const realm = this.config.KEYCLOAK_REALM_URL ?? this.config.KEYCLOAK_ISSUER;
    const res = await fetch(`${realm}/protocol/openid-connect/token`, {
      method: 'POST',
      body: new URLSearchParams({
        grant_type: 'client_credentials',
        client_id: this.config.KEYCLOAK_CLIENT_ID,
        client_secret: this.config.KEYCLOAK_CLIENT_SECRET,
      }),
      signal: AbortSignal.timeout(5_000),
    });
    if (!res.ok) throw new Error(`Keycloak token endpoint: HTTP ${res.status}`);
    const { access_token, expires_in } = (await res.json()) as {
      access_token: string;
      expires_in: number;
    };
    this.token = { value: access_token, expiresAt: Date.now() + expires_in * 1000 };
    return access_token;
  }
}

/** FastAPI errors: `{detail: string}` or, for validation, `{detail: [{loc, msg}]}`. */
async function detailOf(res: Response): Promise<string> {
  const body = (await res.json().catch(() => null)) as { detail?: unknown } | null;
  const detail = body?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return (detail as Schemas['ValidationError'][])
      .map((issue) => `${issue.loc.slice(1).join('.')}: ${issue.msg}`)
      .join('; ');
  }
  return res.statusText;
}
