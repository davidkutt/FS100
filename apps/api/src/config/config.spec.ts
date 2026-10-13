import { loadConfig } from './config.js';

describe('loadConfig', () => {
  it('applies defaults when nothing is set', () => {
    expect(loadConfig({})).toEqual({
      port: 3000,
      corsOrigins: ['http://localhost:4200'],
      logLevel: 'info',
    });
  });

  it('treats empty values like unset ones', () => {
    expect(loadConfig({ API_PORT: '', CORS_ORIGINS: '', LOG_LEVEL: '' }).port).toBe(3000);
  });

  it('parses a comma-separated origin list', () => {
    const config = loadConfig({ CORS_ORIGINS: 'http://localhost:4200, https://kb.example.com' });
    expect(config.corsOrigins).toEqual(['http://localhost:4200', 'https://kb.example.com']);
  });

  it('rejects an invalid port', () => {
    expect(() => loadConfig({ API_PORT: 'abc' })).toThrow(/API_PORT/);
  });

  it('rejects origins with a path', () => {
    expect(() => loadConfig({ CORS_ORIGINS: 'http://localhost:4200/app' })).toThrow(/CORS_ORIGINS/);
  });

  it('rejects unknown log levels', () => {
    expect(() => loadConfig({ LOG_LEVEL: 'verbose' })).toThrow(/LOG_LEVEL/);
  });
});
