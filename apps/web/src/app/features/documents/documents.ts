import { DatePipe } from '@angular/common';
import { HttpClient, httpResource } from '@angular/common/http';
import {
  Component,
  computed,
  effect,
  type ElementRef,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import type { components } from '@fs100/contracts/api';
import Keycloak from 'keycloak-js';
import { firstValueFrom } from 'rxjs';
import { APP_CONFIG } from '../../core/config';
import { problemDetail } from '../../core/problem';
import { DomainPicker } from '../../shared/domain-picker';

type Document = components['schemas']['Document'];
type Taxonomy = components['schemas']['Taxonomy'];

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
  private readonly taxonomy = httpResource<Taxonomy>(() => `${this.api}/api/taxonomy`);
  protected readonly domains = signal<string[]>([]);
  protected readonly topics = signal<string[]>([]);
  protected readonly topicOptions = computed(() => this.topicsOf(this.domains()));
  /** The document in the label dialog, with its labels while they are edited. */
  protected readonly editing = signal<Document | undefined>(undefined);
  protected readonly editDomains = signal<string[]>([]);
  protected readonly editTopics = signal<string[]>([]);
  protected readonly editTopicOptions = computed(() => this.topicsOf(this.editDomains()));
  protected readonly editError = signal('');
  protected readonly errors = signal<string[]>([]);
  protected readonly uploading = signal(false);
  protected readonly dragging = signal(false);
  protected readonly badge: Record<Document['status'], string> = {
    pending: 'text-bg-secondary',
    queued: 'text-bg-secondary',
    parsing: 'text-bg-info',
    contextualizing: 'text-bg-info',
    embedding: 'text-bg-info',
    ready: 'text-bg-success',
    failed: 'text-bg-danger',
  };

  private readonly labels = viewChild.required<ElementRef<HTMLDialogElement>>('labels');

  constructor() {
    // Ingestion runs as a job: poll until every row is ready or failed (D52).
    effect((onCleanup) => {
      const docs = this.docs.hasValue() ? this.docs.value() : [];
      if (!docs.some((d) => this.working(d))) return;
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
      for (const topic of this.picked(this.topics(), this.topicOptions())) {
        form.append('topics', topic);
      }
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

  protected edit(doc: Document): void {
    this.editing.set(doc);
    this.editDomains.set(doc.domains);
    this.editTopics.set(doc.topics);
    this.editError.set('');
    this.labels().nativeElement.showModal();
  }

  /** Relabels the chunks without re-ingesting (D48). */
  protected async saveLabels(doc: Document): Promise<void> {
    if (!this.editDomains().length) return this.editError.set('Pick at least one domain.');
    const body = {
      domains: this.editDomains(),
      topics: this.picked(this.editTopics(), this.editTopicOptions()),
    };
    try {
      await firstValueFrom(this.http.patch(`${this.api}/api/documents/${doc.id}`, body));
      this.labels().nativeElement.close();
      this.docs.reload();
    } catch (error) {
      this.editError.set(problemDetail(error));
    }
  }

  protected working(doc: Document): boolean {
    return doc.status !== 'ready' && doc.status !== 'failed';
  }

  protected canDelete(doc: Document): boolean {
    return this.isAdmin || (this.canUpload && doc.ownerId === this.keycloak.subject);
  }

  private topicsOf(domains: string[]): string[] {
    const all = this.taxonomy.hasValue() ? this.taxonomy.value().domains : {};
    return Object.entries(all)
      .filter(([domain]) => domains.includes(domain))
      .flatMap(([domain, { topics }]) => Object.keys(topics ?? {}).map((t) => `${domain}/${t}`));
  }

  /** Topics of a domain that was deselected again stay hidden in the picker; drop them. */
  private picked(topics: string[], options: string[]): string[] {
    return topics.filter((topic) => options.includes(topic));
  }
}
