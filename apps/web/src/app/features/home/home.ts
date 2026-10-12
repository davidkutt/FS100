import { Component } from '@angular/core';

export interface LocalService {
  readonly name: string;
  readonly role: string;
  readonly url: string;
}

/**
 * Landing page of the base setup: links to every locally running service.
 * The URLs are the fixed dev port map from plan.md §5; from M1.1 on, browser-facing
 * URLs come from the runtime `config.json` (D17).
 */
@Component({
  selector: 'app-home',
  templateUrl: './home.html',
})
export class Home {
  protected readonly services: readonly LocalService[] = [
    { name: 'API', role: 'NestJS · product API / BFF', url: 'http://localhost:3000/api/hello' },
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
