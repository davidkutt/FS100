import { TestBed } from '@angular/core/testing';
import {
  provideRouter,
  type ActivatedRouteSnapshot,
  type RouterStateSnapshot,
  UrlTree,
} from '@angular/router';
import Keycloak from 'keycloak-js';
import { roleGuard } from './role.guard';

describe('roleGuard', () => {
  function check(roles: string[]): Promise<unknown> {
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        { provide: Keycloak, useValue: { authenticated: true, realmAccess: { roles } } },
      ],
    });
    const route = { data: { role: 'viewer' } } as unknown as ActivatedRouteSnapshot;
    return TestBed.runInInjectionContext(
      () => roleGuard(route, {} as RouterStateSnapshot) as Promise<unknown>,
    );
  }

  it('lets users with the role in', async () => {
    expect(await check(['viewer'])).toBe(true);
  });

  it('sends users without the role to the landing page', async () => {
    const result = await check(['offline_access']);

    expect(result).toBeInstanceOf(UrlTree);
    expect(String(result)).toBe('/');
  });
});
