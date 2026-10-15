import { bootstrapApplication } from '@angular/platform-browser';
import { appConfig } from './app/app.config';
import { App } from './app/app';
import type { AppConfig } from './app/core/config';

fetch('/config.json')
  .then((res) => res.json() as Promise<AppConfig>)
  .then((config) => bootstrapApplication(App, appConfig(config)))
  .catch((err) => console.error(err));
