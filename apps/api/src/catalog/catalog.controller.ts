import { Controller, Get, Inject, Req } from '@nestjs/common';
import { ApiOkResponse } from '@nestjs/swagger';
import type { components } from '@fs100/contracts/ai-service';
import { AiClient } from '../ai-client/ai-client.service.js';
import { type AuthRequest, Roles } from '../auth/auth.guard.js';
import { TAXONOMY, Taxonomy } from './taxonomy.js';

type Schemas = components['schemas'];

/** Relayed lists keep the AI-service shape (`@fs100/contracts/ai-service`), cut to the caller's role. */
@Controller()
@Roles('viewer')
export class CatalogController {
  constructor(
    private readonly ai: AiClient,
    @Inject(TAXONOMY) private readonly taxonomy: Taxonomy,
  ) {}

  @Get('models')
  async models(@Req() req: AuthRequest): Promise<Schemas['ModelInfo'][]> {
    const models = await this.ai.get<Schemas['ModelInfo'][]>('/v1/models', req.id as string);
    // Keycloak expands composite roles, so the minimum role is in the token if it is reached.
    return models.filter((model) => req.user.roles.includes(model.min_role));
  }

  @Get('tools')
  async tools(@Req() req: AuthRequest): Promise<Schemas['ToolInfo'][]> {
    const tools = await this.ai.get<Schemas['ToolInfo'][]>('/v1/tools', req.id as string);
    return tools.filter((tool) => req.user.roles.includes(tool.min_role));
  }

  @Get('taxonomy')
  @ApiOkResponse({ standardSchema: Taxonomy })
  getTaxonomy(): Taxonomy {
    return this.taxonomy;
  }
}
