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

/**
 * Calls the internal AI service (`aud=kb-ai`): as the user through standard token exchange (hop 1,
 * ADR-0009), or as the API's service account (client credentials) for system calls.
 */
@Injectable()
export class AiClient {
  // By subject token; '' is the service account.
  private readonly tokens = new Map<string, { value: string; expiresAt: number }>();

  constructor(@Inject(CONFIG) private readonly config: Config) {}

  async get<T>(path: string, requestId: string): Promise<T> {
    const res = await this.request(path, requestId, { signal: AbortSignal.timeout(5_000) });
    return (await res.json()) as T;
  }

  async search(body: SearchRequest, requestId: string, userToken: string): Promise<SearchResponse> {
    const res = await this.request(
      '/v1/search',
      requestId,
      {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(30_000),
      },
      userToken,
    );
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
  chat(
    body: ChatRequest,
    requestId: string,
    signal: AbortSignal,
    userToken: string,
  ): Promise<Response> {
    return this.request(
      '/v1/chat',
      requestId,
      {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
        signal,
      },
      userToken,
    );
  }

  /**
   * SSE v2 (plan-phase-2 §7.3); aborting `signal` cancels the run like `chat`. A resume exchanges
   * afresh, so the AI service sees the user's roles as they are now (D28).
   */
  agent(
    body: AgentRequest,
    requestId: string,
    signal: AbortSignal,
    userToken: string,
    fresh = false,
  ): Promise<Response> {
    return this.request(
      '/v1/agent',
      requestId,
      {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
        signal,
      },
      userToken,
      fresh,
    );
  }

  /** Non-2xx: client errors keep their status and detail, everything else becomes a 502/504. */
  private async request(
    path: string,
    requestId: string,
    init: Omit<RequestInit, 'headers'> & { headers?: Record<string, string> },
    userToken?: string,
    fresh = false,
  ): Promise<Response> {
    const res = await fetch(new URL(path, this.config.AI_SERVICE_URL), {
      ...init,
      headers: {
        ...init.headers,
        authorization: `Bearer ${await this.token(userToken, fresh)}`,
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

  /** The user's token exchanged for `aud=kb-ai`, or the service account's; both cached. */
  private async token(subject = '', fresh = false): Promise<string> {
    // Renew 150 s early: the AI service exchanges the token again during a run (≤ 120 s, ADR-0007).
    const valid = (token?: { expiresAt: number }) =>
      !!token && token.expiresAt - 150_000 > Date.now();
    const cached = this.tokens.get(subject);
    if (!fresh && valid(cached)) return cached!.value;

    const grant: Record<string, string> = subject
      ? {
          grant_type: 'urn:ietf:params:oauth:grant-type:token-exchange',
          subject_token: subject,
          subject_token_type: 'urn:ietf:params:oauth:token-type:access_token',
          audience: this.config.AI_SERVICE_AUDIENCE,
        }
      : { grant_type: 'client_credentials' };
    const realm = this.config.KEYCLOAK_REALM_URL ?? this.config.KEYCLOAK_ISSUER;
    const res = await fetch(`${realm}/protocol/openid-connect/token`, {
      method: 'POST',
      body: new URLSearchParams({
        ...grant,
        client_id: this.config.KEYCLOAK_CLIENT_ID,
        client_secret: this.config.KEYCLOAK_CLIENT_SECRET,
      }),
      signal: AbortSignal.timeout(5_000),
    });
    if (!res.ok) throw new BadGatewayException(`Keycloak token endpoint: HTTP ${res.status}`);
    const { access_token, expires_in } = (await res.json()) as {
      access_token: string;
      expires_in: number;
    };
    // Expired entries go on every fetch, so the map holds about one entry per active user.
    for (const [key, token] of this.tokens) if (!valid(token)) this.tokens.delete(key);
    this.tokens.set(subject, { value: access_token, expiresAt: Date.now() + expires_in * 1000 });
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
