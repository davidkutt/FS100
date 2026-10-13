import { requestIdFrom } from './request-id.js';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

describe('requestIdFrom', () => {
  it('keeps a safe incoming id', () => {
    expect(requestIdFrom('abc-123_x.y:z')).toBe('abc-123_x.y:z');
  });

  it('uses the first value of a repeated header', () => {
    expect(requestIdFrom(['first', 'second'])).toBe('first');
  });

  it.each([undefined, '', 'has space', 'line\nbreak', 'x'.repeat(129)])(
    'mints a UUID for %j',
    (header) => {
      expect(requestIdFrom(header)).toMatch(UUID);
    },
  );
});
