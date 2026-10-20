import { Module } from '@nestjs/common';
import { AiClientModule } from '../ai-client/ai-client.module.js';
import { CONFIG, type Config } from '../config.js';
import { CatalogController } from './catalog.controller.js';
import { loadTaxonomy, TAXONOMY } from './taxonomy.js';

@Module({
  imports: [AiClientModule],
  controllers: [CatalogController],
  providers: [
    {
      provide: TAXONOMY,
      inject: [CONFIG],
      useFactory: (config: Config) => loadTaxonomy(config.TAXONOMY_CONFIG),
    },
  ],
  exports: [TAXONOMY],
})
export class CatalogModule {}
