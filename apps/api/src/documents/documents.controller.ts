import {
  Body,
  Controller,
  Delete,
  Get,
  HttpCode,
  Param,
  ParseUUIDPipe,
  Post,
  Req,
  UploadedFile,
  UseInterceptors,
} from '@nestjs/common';
import { FileInterceptor } from '@nestjs/platform-express';
import { ApiAcceptedResponse, ApiConsumes, ApiOkResponse } from '@nestjs/swagger';
import { z } from 'zod';
import type { Domain } from '../ai-client/ai-client.service.js';
import { type AuthRequest, Roles } from '../auth/auth.guard.js';
import { DOCUMENT_STATUSES, type Document } from '../db/schema.js';
import { DocumentsService, type Upload } from './documents.service.js';

const DOMAINS = [
  'db',
  'dev',
  'cloud',
  'devops',
  'mlops',
  'ai',
  'security',
  'architecture',
  'sre',
] as const satisfies readonly Domain[];
const DomainSchema = z.enum(DOMAINS);

const UploadBody = z
  .object({
    // Multer moves the file to `req.file`; it is listed only for the OpenAPI document.
    file: z.unknown().optional().meta({ type: 'string', format: 'binary' }),
    // Multer turns `domains[]` (or a repeated `domains`) into an array, a single `domains` into a string.
    domains: z
      .array(DomainSchema)
      .min(1)
      .or(DomainSchema.transform((domain) => [domain])),
  })
  .meta({ required: ['file', 'domains'] });

/** Response contract for the OpenAPI document; `test/documents.e2e-spec.ts` checks rows against it. */
export const DocumentDto = z
  .object({
    id: z.uuid(),
    ownerId: z.string(),
    ownerName: z.string(),
    filename: z.string(),
    mime: z.string(),
    sizeBytes: z.int(),
    sha256: z.string(),
    domains: z.array(DomainSchema),
    status: z.enum(DOCUMENT_STATUSES),
    error: z.string().nullable(),
    chunkCount: z.int().nullable(),
    pageCount: z.int().nullable(),
    embeddingModel: z.string().nullable(),
    createdAt: z.iso.datetime({ offset: true }),
    updatedAt: z.iso.datetime({ offset: true }),
  })
  .meta({ id: 'Document' });

@Controller('documents')
export class DocumentsController {
  constructor(private readonly documents: DocumentsService) {}

  @Get()
  @Roles('viewer')
  @ApiOkResponse({ standardSchema: z.array(DocumentDto) })
  list(): Promise<Document[]> {
    return this.documents.list();
  }

  /** 202: ingestion runs in the background; poll the list until the status is terminal (D7). */
  @Post()
  @Roles('editor')
  @HttpCode(202)
  @UseInterceptors(FileInterceptor('file'))
  @ApiConsumes('multipart/form-data')
  @ApiAcceptedResponse({ standardSchema: z.object({ id: z.uuid() }) })
  upload(
    @Req() req: AuthRequest,
    @UploadedFile() file: Upload | undefined,
    @Body({ schema: UploadBody }) body: z.infer<typeof UploadBody>,
  ): Promise<{ id: string }> {
    return this.documents.upload(req.user, file, body.domains, req.id as string);
  }

  @Delete(':id')
  @Roles('editor')
  @HttpCode(204)
  remove(@Req() req: AuthRequest, @Param('id', ParseUUIDPipe) id: string): Promise<void> {
    return this.documents.remove(req.user, id, req.id as string);
  }
}
