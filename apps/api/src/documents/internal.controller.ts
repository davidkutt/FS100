import { Body, Controller, HttpCode, Post, Req } from '@nestjs/common';
import { ApiAcceptedResponse } from '@nestjs/swagger';
import { z } from 'zod';
import { type AuthRequest, ServiceRole } from '../auth/auth.guard.js';
import { DomainSchema } from '../catalog/taxonomy.js';
import { DocumentsService } from './documents.service.js';

const FromUrl = z
  .object({
    url: z.url({ protocol: /^https?$/ }),
    domains: z.array(DomainSchema).min(1),
    onBehalfOf: z.object({ sub: z.string().min(1), name: z.string().min(1) }),
  })
  .meta({ id: 'DocumentFromUrl' });

/** For service accounts, outside `/api`: the documented trusted-subsystem exception (D36). */
@Controller('internal/documents')
export class InternalDocumentsController {
  constructor(private readonly documents: DocumentsService) {}

  /** 202 like an upload: the URL is fetched now, the ingest runs in the background. */
  @Post('from-url')
  @ServiceRole('ingest-on-behalf')
  @HttpCode(202)
  @ApiAcceptedResponse({
    standardSchema: z.object({ id: z.uuid(), status: z.literal('pending') }),
  })
  fromUrl(
    @Req() req: AuthRequest,
    @Body({ schema: FromUrl }) body: z.infer<typeof FromUrl>,
  ): Promise<{ id: string; status: 'pending' }> {
    const { onBehalfOf, url, domains } = body;
    return this.documents.fromUrl(req.user, onBehalfOf, url, domains, req.id as string);
  }
}
