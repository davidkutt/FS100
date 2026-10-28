// Memory budget check (plan-phase-3.md D50): RSS per app incl. child processes, then Docker.
// Usage: pnpm mem   (apps as `pnpm dev` starts them; in Mode B they show up under Docker)
import { execFileSync } from 'node:child_process';
import { totalmem } from 'node:os';

const apps = { 'ai-service': /ai_service\.main/, api: /@grove\/api /, web: /@grove\/web / };
const gb = (bytes) => `${(bytes / 1e9).toFixed(2)} GB`;

const procs = new Map();
for (const line of execFileSync('ps', ['-axo', 'pid=,ppid=,rss=,command='], { encoding: 'utf8' })
  .trim()
  .split('\n')) {
  const [, pid, ppid, rss, command] = line.match(/^\s*(\d+)\s+(\d+)\s+(\d+)\s+(.*)$/);
  procs.set(pid, { ppid, rss: Number(rss) * 1024, command });
}

// uvicorn's reload worker, Nest's child and esbuild don't name their app; their ancestors do.
const appOf = (pid) => {
  for (let p = procs.get(pid); p; p = procs.get(p.ppid)) {
    const name = Object.keys(apps).find((app) => apps[app].test(p.command));
    if (name) return name;
  }
};
const totals = Object.fromEntries(Object.keys(apps).map((app) => [app, { rss: 0, n: 0 }]));
for (const [pid, p] of procs) {
  const app = appOf(pid);
  if (app) Object.assign(totals[app], { rss: totals[app].rss + p.rss, n: totals[app].n + 1 });
}

console.log(`Host RAM ${gb(totalmem())}\n\nApps (RSS incl. child processes)`);
for (const [app, { rss, n }] of Object.entries(totals))
  console.log(`  ${app.padEnd(12)} ${n ? `${gb(rss)}  (${n} processes)` : 'not running'}`);

try {
  const vm = execFileSync('docker', ['info', '--format', '{{.MemTotal}}'], { encoding: 'utf8' });
  console.log(`\nDocker VM ${gb(Number(vm))}`);
  execFileSync('docker', ['stats', '--no-stream', '--format', 'table {{.Name}}\t{{.MemUsage}}'], {
    stdio: 'inherit',
  });
} catch {
  console.log('\nDocker is not running.');
}
