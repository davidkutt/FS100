import { Module } from '@nestjs/common';
import { AiClient } from './ai-client.service.js';

@Module({
  providers: [AiClient],
  exports: [AiClient],
})
export class AiClientModule {}
