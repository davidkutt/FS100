import { KeyValuePipe } from '@angular/common';
import { httpResource } from '@angular/common/http';
import { Component, computed, inject } from '@angular/core';
import { APP_CONFIG } from '../../core/config';

export interface LocalService {
  readonly name: string;
  readonly role: string;
  readonly url: string;
}

export interface Me {
  sub: string;
  name: string;
  roles: string[];
}

/** Landing page: who is signed in, the admin status card and dev links to the local services. */
@Component({
  selector: 'app-home',
  imports: [KeyValuePipe],
  templateUrl: './home.html',
})
export class Home {
  private readonly api = inject(APP_CONFIG).apiBaseUrl;

  protected readonly me = httpResource<Me>(() => `${this.api}/api/me`);
  protected readonly isAdmin = computed(
    () => this.me.hasValue() && this.me.value().roles.includes('admin'),
  );
  protected readonly status = httpResource<Record<string, string>>(() =>
    this.isAdmin() ? `${this.api}/api/status` : undefined,
  );

  protected readonly services: readonly LocalService[] = [
    { name: 'API', role: 'NestJS · product API / BFF', url: 'http://localhost:3000/healthz' },
    {
      name: 'AI service',
      role: 'FastAPI · RAG, evals, tracing',
      url: 'http://localhost:8000/docs',
    },
    { name: 'Keycloak', role: 'Identity · realm "kb"', url: 'http://localhost:8080/admin/' },
    { name: 'Qdrant', role: 'Vector store · dashboard', url: 'http://localhost:6333/dashboard' },
    { name: 'Phoenix', role: 'LLM tracing · OTLP', url: 'http://localhost:6006' },
  ];
}
