import { InjectionToken } from '@angular/core';

/**
 * Browser-facing settings, loaded from `/config.json` before bootstrap (plan.md D17), so the same
 * build runs locally, on k3d and on Azure. In development the file comes from `public/config.json`;
 * in the container nginx renders it from the `WEB_*` variables (M1.6).
 */
export interface RuntimeConfig {
  readonly keycloakUrl: string;
  readonly keycloakRealm: string;
  readonly keycloakClientId: string;
  readonly apiBaseUrl: string;
  /** Phoenix UI for dev-mode trace links; empty = hidden. */
  readonly phoenixUrl: string;
}

export const RUNTIME_CONFIG = new InjectionToken<RuntimeConfig>('RUNTIME_CONFIG');

const REQUIRED = ['keycloakUrl', 'keycloakRealm', 'keycloakClientId', 'apiBaseUrl'] as const;

export async function loadRuntimeConfig(
  fetchFn: typeof fetch = fetch,
  url = '/config.json',
): Promise<RuntimeConfig> {
  const response = await fetchFn(url, { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Could not load ${url} (HTTP ${response.status})`);
  }
  return parseRuntimeConfig(await response.json());
}

export function parseRuntimeConfig(raw: unknown): RuntimeConfig {
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) {
    throw new Error('config.json must contain a JSON object');
  }
  const values = raw as Record<string, unknown>;
  const text = (key: string): string => {
    const value = values[key];
    return typeof value === 'string' ? value.trim() : '';
  };
  const missing = REQUIRED.filter((key) => text(key) === '');
  if (missing.length > 0) {
    throw new Error(`config.json is missing: ${missing.join(', ')}`);
  }
  const url = (key: string) => text(key).replace(/\/+$/, '');
  return {
    keycloakUrl: url('keycloakUrl'),
    keycloakRealm: text('keycloakRealm'),
    keycloakClientId: text('keycloakClientId'),
    apiBaseUrl: url('apiBaseUrl'),
    phoenixUrl: url('phoenixUrl'),
  };
}
