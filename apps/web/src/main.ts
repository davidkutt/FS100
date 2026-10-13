import { bootstrapApplication } from '@angular/platform-browser';
import { App } from './app/app';
import { appConfig } from './app/app.config';
import { loadRuntimeConfig, RUNTIME_CONFIG } from './app/core/config/runtime-config';

loadRuntimeConfig()
  .then((config) =>
    bootstrapApplication(App, {
      ...appConfig,
      providers: [...appConfig.providers, { provide: RUNTIME_CONFIG, useValue: config }],
    }),
  )
  .catch((error: unknown) => {
    console.error(error);
    const message = error instanceof Error ? error.message : String(error);
    document.body.textContent = `FS100 could not start: ${message}`;
  });
