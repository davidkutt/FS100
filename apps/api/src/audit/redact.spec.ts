import { redact } from './redact.js';

describe('redact', () => {
  it('masks secret-looking keys at any depth and cuts long strings', () => {
    const args = {
      title: 'Flaky test',
      body: 'x'.repeat(300),
      auth: { apiKey: 'k', password: 'p', user: 'bob' },
      labels: ['bug', { token: 't' }],
      count: 3,
    };

    expect(redact(args)).toEqual({
      title: 'Flaky test',
      body: `${'x'.repeat(200)}…`,
      auth: { apiKey: '[redacted]', password: '[redacted]', user: 'bob' },
      labels: ['bug', { token: '[redacted]' }],
      count: 3,
    });
  });
});
