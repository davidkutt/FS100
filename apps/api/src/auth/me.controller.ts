import { Controller, Get, Req } from '@nestjs/common';
import { ApiOkResponse } from '@nestjs/swagger';
import { type AuthRequest, AuthUser } from './auth.guard.js';

@Controller('me')
export class MeController {
  @Get()
  @ApiOkResponse({ standardSchema: AuthUser })
  me(@Req() req: AuthRequest): AuthUser {
    return req.user;
  }
}
