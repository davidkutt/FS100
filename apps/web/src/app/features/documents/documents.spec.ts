import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { type ComponentFixture, TestBed } from '@angular/core/testing';
import Keycloak from 'keycloak-js';
import { APP_CONFIG } from '../../core/config';
import { Documents } from './documents';

const doc = (id: string, ownerId: string, filename: string) => ({
  id,
  ownerId,
  ownerName: ownerId,
  filename,
  mime: 'text/markdown',
  sizeBytes: 1,
  sha256: id.repeat(64),
  domains: ['devops'],
  topics: [],
  status: 'ready',
  version: 1,
  jobId: '1',
  error: null,
  chunkCount: 3,
  pageCount: null,
  embeddingModel: 'm',
  createdAt: '2026-10-18T10:00:00Z',
  updatedAt: '2026-10-18T10:00:00Z',
});

const TAXONOMY = {
  version: 1,
  domains: {
    devops: { description: 'Delivery', topics: { 'ci-cd': 'Pipelines', iac: 'Terraform' } },
    sre: { description: 'Reliability', topics: {} },
  },
};

describe('Documents', () => {
  let http: HttpTestingController;
  let fixture: ComponentFixture<Documents>;

  async function render(
    roles: string[],
    docs = [doc('a', 'bob', 'mine.md'), doc('b', 'alice', 'theirs.md')],
  ): Promise<HTMLElement> {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: APP_CONFIG, useValue: { apiBaseUrl: 'http://api' } },
        {
          provide: Keycloak,
          useValue: { subject: 'bob', hasRealmRole: (role: string) => roles.includes(role) },
        },
      ],
    });
    HTMLDialogElement.prototype.showModal = vi.fn();
    HTMLDialogElement.prototype.close = vi.fn();
    fixture = TestBed.createComponent(Documents);
    TestBed.tick();
    http = TestBed.inject(HttpTestingController);
    http.expectOne('http://api/api/taxonomy').flush(TAXONOMY);
    http.expectOne('http://api/api/documents').flush(docs);
    await fixture.whenStable();
    return fixture.nativeElement as HTMLElement;
  }

  const deleteButtons = (page: HTMLElement) =>
    Array.from(page.querySelectorAll('button')).map((b) => b.getAttribute('aria-label'));

  it('is read-only for viewers', async () => {
    const page = await render(['viewer']);

    expect(page.querySelectorAll('tbody tr')).toHaveLength(2);
    expect(page.querySelector('input[type=file]')).toBeNull();
    expect(deleteButtons(page)).toEqual([]);
  });

  it('lets editors upload and delete their own documents only', async () => {
    const page = await render(['editor', 'viewer']);

    expect(page.querySelector('input[type=file]')).not.toBeNull();
    expect(deleteButtons(page)).toEqual(['Edit labels of mine.md', 'Delete mine.md']);
  });

  it('shows the job state and polls until the job has ended', async () => {
    const working = { ...doc('a', 'bob', 'mine.md'), status: 'embedding' };
    const page = await render(['editor', 'viewer'], [working]);
    const badge = () => page.querySelector('tbody td:nth-child(3) .badge')?.textContent?.trim();
    const labels = page.querySelector<HTMLButtonElement>('[aria-label="Edit labels of mine.md"]')!;

    expect(badge()).toBe('embedding');
    expect(page.querySelector('tbody .spinner-border')).not.toBeNull();
    expect(labels.disabled).toBe(true);
    const poll = await vi.waitFor(() => http.expectOne('http://api/api/documents'), {
      timeout: 3000,
    });
    poll.flush([doc('a', 'bob', 'mine.md')]);
    await fixture.whenStable();

    expect(badge()).toBe('ready');
  });

  it('offers the sub-topics of the picked domains and relabels without re-uploading', async () => {
    const page = await render(['editor', 'viewer']);
    const click = async (selector: string) => {
      page.querySelector<HTMLElement>(selector)!.click();
      await fixture.whenStable();
    };
    const labelsOf = (fieldset: Element) =>
      Array.from(fieldset.querySelectorAll('label')).map((label) => label.textContent?.trim());

    await click('button[aria-label="Edit labels of mine.md"]');
    const dialog = page.querySelector('dialog')!;
    const [domains, topics] = Array.from(dialog.querySelectorAll('fieldset'));
    expect(labelsOf(topics)).toEqual(['devops/ci-cd', 'devops/iac']);
    topics.querySelector<HTMLInputElement>('input[id$="devops/iac"]')!.click();
    domains.querySelector<HTMLInputElement>('input[id$="sre"]')!.click();
    await fixture.whenStable();
    await click('dialog button[type=submit]');

    const patch = http.expectOne('http://api/api/documents/a');
    expect(patch.request.method).toBe('PATCH');
    expect(patch.request.body).toEqual({ domains: ['devops', 'sre'], topics: ['devops/iac'] });
  });
});
