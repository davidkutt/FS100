import { DatePipe } from '@angular/common';
import { HttpClient, httpResource } from '@angular/common/http';
import { Component, effect, inject, signal } from '@angular/core';
import type { components } from '@fs100/contracts/api';
import Keycloak from 'keycloak-js';
import { firstValueFrom } from 'rxjs';
import { APP_CONFIG } from '../../core/config';
import { problemDetail } from '../../core/problem';
import { type Domain, DomainPicker } from '../../shared/domain-picker';

type Document = components['schemas']['Document'];

/** Upload, list and delete documents; the controls follow the roles, the API enforces them (D6). */
@Component({
  selector: 'app-documents',
  imports: [DatePipe, DomainPicker],
  templateUrl: './documents.html',
})
export class Documents {
  private readonly api = inject(APP_CONFIG).apiBaseUrl;
  private readonly http = inject(HttpClient);
  private readonly keycloak = inject(Keycloak);
  private readonly isAdmin = this.keycloak.hasRealmRole('admin');

  protected readonly canUpload = this.keycloak.hasRealmRole('editor');
  protected readonly docs = httpResource<Document[]>(() => `${this.api}/api/documents`);
  protected readonly domains = signal<Domain[]>([]);
  protected readonly errors = signal<string[]>([]);
  protected readonly uploading = signal(false);
  protected readonly dragging = signal(false);
  protected readonly badge: Record<Document['status'], string> = {
    pending: 'text-bg-secondary',
    processing: 'text-bg-info',
    ready: 'text-bg-success',
    failed: 'text-bg-danger',
  };

  constructor() {
    // Ingestion runs in the background: poll until every row is ready or failed (plan.md §5).
    effect((onCleanup) => {
      const docs = this.docs.hasValue() ? this.docs.value() : [];
      if (!docs.some((d) => d.status === 'pending' || d.status === 'processing')) return;
      const timer = setTimeout(() => this.docs.reload(), 2000);
      onCleanup(() => clearTimeout(timer));
    });
  }

  protected async upload(list: FileList | null | undefined): Promise<void> {
    // Copied before the first await: the template clears the input right after this call.
    const files = Array.from(list ?? []);
    this.dragging.set(false);
    if (!files.length) return;
    if (!this.domains().length) return this.errors.set(['Pick at least one domain first.']);
    this.errors.set([]);
    this.uploading.set(true);
    for (const file of files) {
      const form = new FormData();
      form.append('file', file);
      for (const domain of this.domains()) form.append('domains', domain);
      try {
        await firstValueFrom(this.http.post(`${this.api}/api/documents`, form));
      } catch (error) {
        this.errors.update((errors) => [...errors, `${file.name}: ${problemDetail(error)}`]);
      }
      this.docs.reload();
    }
    this.uploading.set(false);
  }

  protected async remove(doc: Document): Promise<void> {
    if (!confirm(`Delete "${doc.filename}" and its vectors?`)) return;
    try {
      await firstValueFrom(this.http.delete(`${this.api}/api/documents/${doc.id}`));
    } catch (error) {
      this.errors.set([`${doc.filename}: ${problemDetail(error)}`]);
    }
    this.docs.reload();
  }

  protected canDelete(doc: Document): boolean {
    return this.isAdmin || (this.canUpload && doc.ownerId === this.keycloak.subject);
  }
}
