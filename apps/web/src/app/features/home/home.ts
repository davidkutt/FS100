import { Component, inject, isDevMode } from '@angular/core';
import { RUNTIME_CONFIG } from '../../core/config/runtime-config';

export interface LocalService {
  readonly name: string;
  readonly role: string;
  readonly url: string;
}

/**
 * Landing page of the base setup: links to the running services. Browser-facing URLs come from
 * the runtime config; the AI service and Qdrant are internal (never browser-facing), so their
 * links exist only in development, on the fixed port map from plan.md §5.
 */
@Component({
  selector: 'app-home',
  templateUrl: './home.html',
})
export class Home {
  private readonly config = inject(RUNTIME_CONFIG);

  protected readonly services: readonly LocalService[] = [
    {
      name: 'API',
      role: 'NestJS · product API / BFF',
      url: `${this.config.apiBaseUrl}/api/hello`,
      show: true,
    },
    {
      name: 'AI service',
      role: 'FastAPI · RAG, evals, tracing',
      url: 'http://localhost:8000/docs',
      show: isDevMode(),
    },
    {
      name: 'Keycloak',
      role: `Identity · realm "${this.config.keycloakRealm}"`,
      url: `${this.config.keycloakUrl}/admin/`,
      show: true,
    },
    {
      name: 'Qdrant',
      role: 'Vector store · dashboard',
      url: 'http://localhost:6333/dashboard',
      show: isDevMode(),
    },
    {
      name: 'Phoenix',
      role: 'LLM tracing · OTLP',
      url: this.config.phoenixUrl,
      show: this.config.phoenixUrl !== '',
    },
  ]
    .filter((service) => service.show)
    .map(({ name, role, url }) => ({ name, role, url }));
}
