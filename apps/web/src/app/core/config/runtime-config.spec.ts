import { loadRuntimeConfig, parseRuntimeConfig } from './runtime-config';

const valid = {
  keycloakUrl: 'http://localhost:8080/',
  keycloakRealm: 'kb',
  keycloakClientId: 'kb-web',
  apiBaseUrl: 'http://localhost:3000',
  phoenixUrl: 'http://localhost:6006',
};

describe('parseRuntimeConfig', () => {
  it('accepts a complete config and strips trailing slashes from URLs', () => {
    expect(parseRuntimeConfig(valid)).toEqual({ ...valid, keycloakUrl: 'http://localhost:8080' });
  });

  it('treats a missing phoenixUrl as hidden', () => {
    const withoutPhoenix: Record<string, string> = { ...valid };
    delete withoutPhoenix['phoenixUrl'];
    expect(parseRuntimeConfig(withoutPhoenix).phoenixUrl).toBe('');
  });

  it('names every missing required key', () => {
    expect(() => parseRuntimeConfig({ keycloakRealm: 'kb', apiBaseUrl: ' ' })).toThrow(
      'config.json is missing: keycloakUrl, keycloakClientId, apiBaseUrl',
    );
  });

  it.each([null, [], 'text'])('rejects %j', (raw) => {
    expect(() => parseRuntimeConfig(raw)).toThrow('must contain a JSON object');
  });
});

describe('loadRuntimeConfig', () => {
  it('fetches /config.json without caching', async () => {
    const fetchFn = vi.fn(async () => new Response(JSON.stringify(valid)));

    await expect(loadRuntimeConfig(fetchFn)).resolves.toMatchObject({ keycloakRealm: 'kb' });
    expect(fetchFn).toHaveBeenCalledWith('/config.json', { cache: 'no-store' });
  });

  it('reports HTTP errors', async () => {
    const fetchFn = vi.fn(async () => new Response('not found', { status: 404 }));

    await expect(loadRuntimeConfig(fetchFn)).rejects.toThrow(
      'Could not load /config.json (HTTP 404)',
    );
  });
});
