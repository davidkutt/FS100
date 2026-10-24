import {
  Body,
  Controller,
  Delete,
  Get,
  HttpCode,
  Param,
  ParseUUIDPipe,
  Patch,
  Post,
  Req,
  UploadedFile,
  UseInterceptors,
} from '@nestjs/common';
import { FileInterceptor } from '@nestjs/platform-express';
import { ApiAcceptedResponse, ApiConsumes, ApiOkResponse } from '@nestjs/swagger';
import { z } from 'zod';
import { type AuthRequest, Roles } from '../auth/auth.guard.js';
import { DomainSchema } from '../catalog/taxonomy.js';
import { DOCUMENT_STATUSES, type Document } from '../db/schema.js';
import { DocumentsService, type Upload } from './documents.service.js';

const UploadBody = z
  .object({
    // Multer moves the file to `req.file`; it is listed only for the OpenAPI document.
    file: z.unknown().optional().meta({ type: 'string', format: 'binary' }),
    // Multer turns `domains[]` (or a repeated `domains`) into an array, a single `domains` into a string.
    domains: z
      .array(DomainSchema)
      .min(1)
      .or(DomainSchema.transform((domain) => [domain])),
    // `domain/topic` ids from the taxonomy (D48), checked by the service.
    topics: z
      .array(z.string())
      .or(z.string().transform((topic) => [topic]))
      .default([]),
  })
  .meta({ required: ['file', 'domains'] });

const LabelsBody = z
  .object({
    domains: z.array(DomainSchema).min(1).optional(),
    topics: z.array(z.string()).optional(),
  })
  .refine((labels) => labels.domains || labels.topics, 'Give `domains`, `topics` or both')
  .meta({ id: 'DocumentLabels' });
export type LabelsBody = z.infer<typeof LabelsBody>;

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
    topics: z.array(z.string()),
    status: z.enum(DOCUMENT_STATUSES),
    version: z.int(),
    jobId: z.string().nullable(),
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
  list(@Req() req: AuthRequest): Promise<Document[]> {
    return this.documents.list(req.id as string);
  }

  /** 202: the AI service queues the ingest; poll the list until the status is terminal (D52). */
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
    return this.documents.upload(req.user, file, body.domains, body.topics, req.id as string);
  }

  /** Relabels the chunks in Qdrant without re-embedding (D48). */
  @Patch(':id')
  @Roles('editor')
  @ApiOkResponse({ standardSchema: DocumentDto })
  relabel(
    @Req() req: AuthRequest,
    @Param('id', ParseUUIDPipe) id: string,
    @Body({ schema: LabelsBody }) body: LabelsBody,
  ): Promise<Document> {
    return this.documents.relabel(req.user, id, body, req.id as string);
  }

  @Delete(':id')
  @Roles('editor')
  @HttpCode(204)
  remove(@Req() req: AuthRequest, @Param('id', ParseUUIDPipe) id: string): Promise<void> {
    return this.documents.remove(req.user, id, req.id as string);
  }
}
