import { provideHttpClient, withInterceptors, type HttpRequest } from '@angular/common/http';
import { ApplicationConfig, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideRouter, withComponentInputBinding } from '@angular/router';
import {
  CUSTOM_BEARER_TOKEN_INTERCEPTOR_CONFIG,
  customBearerTokenInterceptor,
  provideKeycloak,
} from 'keycloak-angular';
import { routes } from './app.routes';
import { APP_CONFIG, type AppConfig } from './core/config';

export function appConfig(config: AppConfig): ApplicationConfig {
  return {
    providers: [
      provideBrowserGlobalErrorListeners(),
      provideRouter(routes, withComponentInputBinding()),
      { provide: APP_CONFIG, useValue: config },
      provideKeycloak({
        config: {
          url: config.keycloakUrl,
          realm: config.keycloakRealm,
          clientId: config.keycloakClientId,
        },
        initOptions: { onLoad: 'login-required', pkceMethod: 'S256' },
      }),
      // The token goes to our API only; the interceptor refreshes it before each request.
      {
        provide: CUSTOM_BEARER_TOKEN_INTERCEPTOR_CONFIG,
        useValue: [
          {
            shouldAddToken: async (req: HttpRequest<unknown>) =>
              req.url.startsWith(`${config.apiBaseUrl}/api/`),
          },
        ],
      },
      provideHttpClient(withInterceptors([customBearerTokenInterceptor])),
    ],
  };
}
