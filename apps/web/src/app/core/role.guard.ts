import { inject } from '@angular/core';
import { Router, type CanActivateFn } from '@angular/router';
import { createAuthGuard } from 'keycloak-angular';

/** Requires the realm role in the route's `data.role`; the API enforces the same roles (D6). */
export const roleGuard = createAuthGuard<CanActivateFn>(async (route, _state, { grantedRoles }) => {
  const router = inject(Router);
  return grantedRoles.realmRoles.includes(route.data['role']) || router.parseUrl('/');
});
