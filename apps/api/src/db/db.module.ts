import { fileURLToPath } from 'node:url';
import { Global, Logger, Module } from '@nestjs/common';
import { drizzle, type NodePgDatabase } from 'drizzle-orm/node-postgres';
import { migrate } from 'drizzle-orm/node-postgres/migrator';
import { CONFIG, type Config } from '../config.js';

export type Db = NodePgDatabase;
export const DB = Symbol('DB');

// Same depth below the app root from src/db and dist/db.
const migrationsFolder = fileURLToPath(new URL('../../drizzle', import.meta.url));

async function connect(url: string): Promise<Db> {
  // `:memory:` = in-process PGlite (tests, `contracts:generate`), like QDRANT_URL=:memory:.
  if (url === ':memory:') {
    const pglite = await import('drizzle-orm/pglite');
    const migrator = await import('drizzle-orm/pglite/migrator');
    const db = pglite.drizzle({ casing: 'snake_case' });
    await migrator.migrate(db, { migrationsFolder });
    return db as unknown as Db;
  }
  const db = drizzle(url, { casing: 'snake_case' });
  // Without a listener an idle-connection error (e.g. a Postgres restart) crashes the process.
  db.$client.on('error', (error) => new Logger('Db').warn(`Postgres pool: ${error.message}`));
  // shortcut: migrating on boot assumes one API instance; use a migration job before scaling out (P4).
  await migrate(db, { migrationsFolder });
  return db;
}

@Global()
@Module({
  providers: [
    {
      provide: DB,
      inject: [CONFIG],
      useFactory: (config: Config) => connect(config.API_DATABASE_URL),
    },
  ],
  exports: [DB],
})
export class DbModule {}
