import { Controller, Get, Req } from '@nestjs/common';
import type { AuthRequest, AuthUser } from './auth.guard.js';

@Controller('me')
export class MeController {
  @Get()
  me(@Req() req: AuthRequest): AuthUser {
    return req.user;
  }
}
