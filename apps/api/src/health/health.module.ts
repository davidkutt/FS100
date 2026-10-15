import { Module } from '@nestjs/common';
import { AiClientModule } from '../ai-client/ai-client.module.js';
import { HealthController } from './health.controller.js';

@Module({
  imports: [AiClientModule],
  controllers: [HealthController],
})
export class HealthModule {}
