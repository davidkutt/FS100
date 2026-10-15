import { Inject, Injectable } from '@nestjs/common';
import { CONFIG, type Config } from '../config.js';

/** Calls the internal AI service with the API's client-credentials token (`aud=kb-ai`, D5). */
@Injectable()
export class AiClient {
  private token?: { value: string; expiresAt: number };

  constructor(@Inject(CONFIG) private readonly config: Config) {}

  async get<T>(path: string, requestId: string): Promise<T> {
    const res = await fetch(new URL(path, this.config.AI_SERVICE_URL), {
      headers: { authorization: `Bearer ${await this.serviceToken()}`, 'x-request-id': requestId },
      signal: AbortSignal.timeout(5_000),
    });
    if (!res.ok) throw new Error(`AI service GET ${path}: HTTP ${res.status}`);
    return (await res.json()) as T;
  }

  private async serviceToken(): Promise<string> {
    // Renew 30 s early so a token never expires in flight.
    if (this.token && this.token.expiresAt - 30_000 > Date.now()) return this.token.value;

    const res = await fetch(`${this.config.KEYCLOAK_ISSUER}/protocol/openid-connect/token`, {
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
