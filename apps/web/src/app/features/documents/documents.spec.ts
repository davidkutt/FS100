import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
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
  status: 'ready',
  error: null,
  chunkCount: 3,
  pageCount: null,
  embeddingModel: 'm',
  createdAt: '2026-10-18T10:00:00Z',
  updatedAt: '2026-10-18T10:00:00Z',
});

describe('Documents', () => {
  async function render(roles: string[]): Promise<HTMLElement> {
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
    const fixture = TestBed.createComponent(Documents);
    TestBed.tick();
    TestBed.inject(HttpTestingController)
      .expectOne('http://api/api/documents')
      .flush([doc('a', 'bob', 'mine.md'), doc('b', 'alice', 'theirs.md')]);
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
    expect(deleteButtons(page)).toEqual(['Delete mine.md']);
  });
});
