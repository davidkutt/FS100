import { TestBed } from '@angular/core/testing';
import { RUNTIME_CONFIG, type RuntimeConfig } from '../../core/config/runtime-config';
import { Home } from './home';

const config: RuntimeConfig = {
  keycloakUrl: 'https://login.example.com',
  keycloakRealm: 'kb',
  keycloakClientId: 'kb-web',
  apiBaseUrl: 'https://api.example.com',
  phoenixUrl: 'https://phoenix.example.com',
};

async function renderLinks(runtimeConfig: RuntimeConfig): Promise<string[]> {
  TestBed.configureTestingModule({
    providers: [{ provide: RUNTIME_CONFIG, useValue: runtimeConfig }],
  });
  const fixture = TestBed.createComponent(Home);
  await fixture.whenStable();
  return Array.from(
    (fixture.nativeElement as HTMLElement).querySelectorAll<HTMLAnchorElement>('a.stretched-link'),
  ).map((a) => a.href);
}

describe('Home', () => {
  it('builds browser-facing links from the runtime config', async () => {
    expect(await renderLinks(config)).toEqual([
      'https://api.example.com/api/hello',
      'http://localhost:8000/docs',
      'https://login.example.com/admin/',
      'http://localhost:6333/dashboard',
      'https://phoenix.example.com/',
    ]);
  });

  it('hides Phoenix when phoenixUrl is empty', async () => {
    const links = await renderLinks({ ...config, phoenixUrl: '' });
    expect(links.some((href) => href.includes('phoenix'))).toBe(false);
  });
});
