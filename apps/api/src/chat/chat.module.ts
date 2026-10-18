import { Module } from '@nestjs/common';
import { AiClientModule } from '../ai-client/ai-client.module.js';
import { ChatController } from './chat.controller.js';

@Module({
  imports: [AiClientModule],
  controllers: [ChatController],
})
export class ChatModule {}
