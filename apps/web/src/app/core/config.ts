import { InjectionToken } from '@angular/core';

/** Runtime config from `/config.json`, loaded before bootstrap (D17); dev values in `public/`. */
export interface AppConfig {
  keycloakUrl: string;
  keycloakRealm: string;
  keycloakClientId: string;
  apiBaseUrl: string;
}

export const APP_CONFIG = new InjectionToken<AppConfig>('APP_CONFIG');
