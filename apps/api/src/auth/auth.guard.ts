import {
  type CanActivate,
  type ExecutionContext,
  ForbiddenException,
  Inject,
  Injectable,
  SetMetadata,
  UnauthorizedException,
} from '@nestjs/common';
import { Reflector } from '@nestjs/core';
import type { Request } from 'express';
import { errors, jwtVerify, type JWTVerifyGetKey } from 'jose';
import { z } from 'zod';
import { CONFIG, type Config } from '../config.js';

export const ROLES = ['viewer', 'editor', 'admin'] as const;
export type Role = (typeof ROLES)[number];

export const AuthUser = z
  .object({ sub: z.string(), name: z.string(), roles: z.array(z.enum(ROLES)) })
  .meta({ id: 'User' });
export type AuthUser = z.infer<typeof AuthUser>;

/** `accessToken` is the bearer, exchanged for calls to the AI service on the user's behalf. */
export type AuthRequest = Request & { user: AuthUser; accessToken: string };

interface KeycloakClaims {
  name?: string;
  preferred_username?: string;
  realm_access?: { roles?: string[] };
  resource_access?: Record<string, { roles?: string[] }>;
}

export const Public = () => SetMetadata('public', true);
/** Any of the given realm roles; composites (admin ⊃ editor ⊃ viewer) are expanded by Keycloak. */
export const Roles = (...roles: Role[]) => SetMetadata('roles', roles);
/** A client role of the API that only service accounts hold, e.g. `ingest-on-behalf` (D36). */
export const ServiceRole = (role: string) => SetMetadata('serviceRole', role);

export const JWKS = Symbol('JWKS');

/** Global guard: every route needs a Keycloak access token for `aud=kb-api` unless `@Public()`. */
@Injectable()
export class AuthGuard implements CanActivate {
  constructor(
    private readonly reflector: Reflector,
    @Inject(CONFIG) private readonly config: Config,
    @Inject(JWKS) private readonly jwks: JWTVerifyGetKey,
  ) {}

  async canActivate(context: ExecutionContext): Promise<boolean> {
    const targets = [context.getHandler(), context.getClass()];
    if (this.reflector.getAllAndOverride<boolean>('public', targets)) return true;

    const req = context.switchToHttp().getRequest<AuthRequest>();
    const [scheme, token] = req.headers.authorization?.split(' ') ?? [];
    if (scheme !== 'Bearer' || !token) throw new UnauthorizedException('Missing bearer token');

    const { payload } = await jwtVerify<KeycloakClaims>(token, this.jwks, {
      issuer: this.config.KEYCLOAK_ISSUER,
      audience: this.config.KEYCLOAK_AUDIENCE,
      algorithms: ['RS256'],
      requiredClaims: ['exp', 'sub'],
    }).catch((error: unknown) => {
      if (error instanceof errors.JOSEError) throw new UnauthorizedException(error.message);
      throw error;
    });

    const sub = payload.sub as string;
    const roles = ROLES.filter((role) => payload.realm_access?.roles?.includes(role));
    req.user = { sub, name: payload.name ?? payload.preferred_username ?? sub, roles };
    req.accessToken = token;

    const required = this.reflector.getAllAndOverride<Role[] | undefined>('roles', targets);
    if (required && !required.some((role) => roles.includes(role))) throw new ForbiddenException();
    const service = this.reflector.getAllAndOverride<string | undefined>('serviceRole', targets);
    const clientRoles = payload.resource_access?.[this.config.KEYCLOAK_CLIENT_ID]?.roles;
    if (service && !clientRoles?.includes(service)) throw new ForbiddenException();
    return true;
  }
}
