import { Module } from '@nestjs/common';
import { AiClientModule } from '../ai-client/ai-client.module.js';
import { ChatThrottle } from './chat-throttle.js';
import { ChatController } from './chat.controller.js';

@Module({
  imports: [AiClientModule],
  controllers: [ChatController],
  providers: [ChatThrottle],
  exports: [ChatThrottle],
})
export class ChatModule {}
