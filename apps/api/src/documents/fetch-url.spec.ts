import { once } from 'node:events';
import { createServer } from 'node:http';
import type { AddressInfo, LookupFunction } from 'node:net';
import { fetchDocument, publicOnly } from './fetch-url.js';

/** Every name resolves to the local test server, like a public host would. */
const local: LookupFunction = (_hostname, options, callback) => {
  const address = { address: '127.0.0.1', family: 4 };
  if (options.all) return (callback as (e: null, a: (typeof address)[]) => void)(null, [address]);
  callback(null, address.address, address.family);
};

describe('fetchDocument', () => {
  let port = 0;
  const server = createServer((req, res) => {
    if (req.url === '/hop') return void res.writeHead(301, { location: '/a.md' }).end();
    if (req.url === '/away') {
      return void res.writeHead(302, { location: `http://evil.test:${port}/a.md` }).end();
    }
    if (req.url === '/big.md') return void res.end('x'.repeat(2048));
    if (req.url === '/a.md') return void res.end('# A\n');
    res.writeHead(404).end();
  });

  beforeAll(async () => {
    server.listen(0, '127.0.0.1');
    await once(server, 'listening');
    port = (server.address() as AddressInfo).port;
  });

  afterAll(() => server.close());

  const get = (path: string, host = 'docs.test', lookup = local) =>
    fetchDocument(new URL(`http://${host}:${port}${path}`), [`${host}:${port}`], 1024, lookup);

  it('downloads from an allowed host, following redirects that stay on the list', async () => {
    const file = await get('/hop');

    expect(file).toMatchObject({ originalname: 'a.md', size: 4 });
    expect(file.buffer.toString()).toBe('# A\n');
  });

  it.each([
    [
      'a host off the list',
      () => fetchDocument(new URL('https://example.com/a.md'), [], 1024, local),
      400,
      'Host example.com is not allowed',
    ],
    ['a redirect off the list', () => get('/away'), 400, 'Host evil.test:'],
    ['an IP literal', () => get('/a.md', '127.0.0.1'), 400, 'IP addresses are not fetched'],
    [
      'a name for a private address',
      () => get('/a.md', 'localhost', publicOnly),
      400,
      'localhost is not a public address',
    ],
    [
      'another scheme',
      () => fetchDocument(new URL('file:///etc/passwd'), [''], 1024, local),
      400,
      'Only http(s)',
    ],
    ['more than the size limit', () => get('/big.md'), 413, 'larger than 1024 bytes'],
    ['an error status', () => get('/gone.md'), 502, 'answered HTTP 404'],
  ])('refuses %s', async (_case, fetch, status, message) => {
    await expect(fetch()).rejects.toMatchObject({
      status,
      message: expect.stringContaining(message),
    });
  });
});
