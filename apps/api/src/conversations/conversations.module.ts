import { Module } from '@nestjs/common';
import { AiClientModule } from '../ai-client/ai-client.module.js';
import { ChatModule } from '../chat/chat.module.js';
import { UsageModule } from '../usage/usage.module.js';
import { ApprovalsService } from './approvals.service.js';
import { ConversationsController } from './conversations.controller.js';
import { ConversationsService } from './conversations.service.js';

@Module({
  imports: [AiClientModule, ChatModule, UsageModule],
  controllers: [ConversationsController],
  providers: [ConversationsService, ApprovalsService],
})
export class ConversationsModule {}
