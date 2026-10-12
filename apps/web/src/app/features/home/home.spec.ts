import { TestBed } from '@angular/core/testing';
import { Home } from './home';

describe('Home', () => {
  it('links to every local service', async () => {
    const fixture = TestBed.createComponent(Home);
    await fixture.whenStable();
    const links = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll<HTMLAnchorElement>(
        'a.stretched-link',
      ),
    ).map((a) => a.href);

    expect(links).toEqual([
      'http://localhost:3000/api/hello',
      'http://localhost:8000/docs',
      'http://localhost:8080/admin/',
      'http://localhost:6333/dashboard',
      'http://localhost:6006/',
    ]);
  });
});
