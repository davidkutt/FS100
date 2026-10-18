import { Module } from '@nestjs/common';
import { MulterModule } from '@nestjs/platform-express';
import { AiClientModule } from '../ai-client/ai-client.module.js';
import { CONFIG, type Config } from '../config.js';
import { DocumentsController } from './documents.controller.js';
import { DocumentsService } from './documents.service.js';

@Module({
  imports: [
    AiClientModule,
    MulterModule.registerAsync({
      inject: [CONFIG],
      useFactory: (config: Config) => ({
        limits: { fileSize: config.UPLOAD_MAX_MB * 1024 * 1024, files: 1 },
        // Browsers send UTF-8 filenames without a charset; multer would read them as latin1.
        defParamCharset: 'utf8',
      }),
    }),
  ],
  controllers: [DocumentsController],
  providers: [DocumentsService],
})
export class DocumentsModule {}
