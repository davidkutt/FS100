import { lookup as dnsLookup, type LookupAddress } from 'node:dns';
import { get as httpGet, type IncomingMessage } from 'node:http';
import { get as httpsGet } from 'node:https';
import { BlockList, isIP, type LookupFunction } from 'node:net';
import { basename } from 'node:path';
import { BadGatewayException, BadRequestException, PayloadTooLargeException } from '@nestjs/common';
import type { Upload } from './documents.service.js';

// Not public unicast (IPv4-mapped IPv6 addresses are checked against the IPv4 ranges).
const PRIVATE = new BlockList();
for (const [net, prefix] of [
  ['0.0.0.0', 8],
  ['10.0.0.0', 8],
  ['100.64.0.0', 10],
  ['127.0.0.0', 8],
  ['169.254.0.0', 16],
  ['172.16.0.0', 12],
  ['192.0.0.0', 24],
  ['192.168.0.0', 16],
  ['198.18.0.0', 15],
  ['224.0.0.0', 3],
] as const) {
  PRIVATE.addSubnet(net, prefix, 'ipv4');
}
for (const [net, prefix] of [
  ['::', 127],
  ['64:ff9b::', 96],
  ['fc00::', 7],
  ['fe80::', 10],
  ['ff00::', 8],
] as const) {
  PRIVATE.addSubnet(net, prefix, 'ipv6');
}

/** DNS lookup that fails for non-public addresses; runs on every connect, so rebinding fails too. */
export const publicOnly: LookupFunction = (hostname, options, callback) =>
  dnsLookup(hostname, { ...options, all: true }, (error, addresses: LookupAddress[]) => {
    const blocked = addresses?.find(({ address, family }) =>
      PRIVATE.check(address, family === 6 ? 'ipv6' : 'ipv4'),
    );
    if (error || blocked) {
      const refused = blocked && new BadRequestException(`${hostname} is not a public address`);
      return callback(refused || error, '', 0);
    }
    if (options.all) return (callback as (e: null, a: LookupAddress[]) => void)(null, addresses);
    callback(null, addresses[0].address, addresses[0].family);
  });

/**
 * Downloads a document for `kb.ingest_url` (SSRF guard, D36): allow-listed hosts on every hop, no IP
 * literals, no private addresses, at most 3 redirects, at most `maxBytes`.
 */
export async function fetchDocument(
  url: URL,
  hosts: string[],
  maxBytes: number,
  lookup: LookupFunction = publicOnly,
  redirects = 3,
): Promise<Upload> {
  if (url.protocol !== 'https:' && url.protocol !== 'http:') {
    throw new BadRequestException(`Only http(s) URLs are fetched, not ${url.protocol}`);
  }
  if (isIP(url.hostname.replace(/^\[|\]$/g, ''))) {
    throw new BadRequestException('IP addresses are not fetched; use an allowed host name');
  }
  if (!hosts.includes(url.host)) throw new BadRequestException(`Host ${url.host} is not allowed`);

  const get = url.protocol === 'https:' ? httpsGet : httpGet;
  const res = await new Promise<IncomingMessage>((resolve, reject) =>
    get(url, { lookup, signal: AbortSignal.timeout(15_000) }, resolve).on('error', reject),
  ).catch((error: unknown) => {
    if (error instanceof BadRequestException) throw error;
    throw new BadGatewayException(`Fetching ${url.host} failed: ${String(error)}`);
  });
  const location = res.headers.location;
  if (res.statusCode && res.statusCode >= 300 && res.statusCode < 400 && location) {
    res.resume();
    if (!redirects) throw new BadGatewayException(`Too many redirects from ${url.host}`);
    return fetchDocument(new URL(location, url), hosts, maxBytes, lookup, redirects - 1);
  }
  if (res.statusCode !== 200) {
    res.resume();
    throw new BadGatewayException(`${url.host} answered HTTP ${res.statusCode}`);
  }
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of res as AsyncIterable<Buffer>) {
    size += chunk.length;
    if (size > maxBytes) {
      res.destroy();
      throw new PayloadTooLargeException(`The document is larger than ${maxBytes} bytes`);
    }
    chunks.push(chunk);
  }
  // The extension decides the type, as for uploads; a page served as HTML is HTML whatever its path.
  const name = basename(url.pathname) || 'index';
  const html = /^text\/html\b/i.test(res.headers['content-type'] ?? '') && !/\.html$/i.test(name);
  return { originalname: html ? `${name}.html` : name, buffer: Buffer.concat(chunks), size };
}
