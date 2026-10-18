import { STATUS_CODES } from 'node:http';
import {
  type ArgumentsHost,
  Catch,
  type ExceptionFilter,
  HttpException,
  Logger,
} from '@nestjs/common';
import type { Response } from 'express';

/** Every error as RFC 9457 `application/problem+json` (plan.md §7.2). */
@Catch()
export class ProblemFilter implements ExceptionFilter {
  private readonly logger = new Logger(ProblemFilter.name);

  catch(exception: unknown, host: ArgumentsHost): void {
    const res = host.switchToHttp().getResponse<Response>();
    const known = exception instanceof HttpException;
    const status = known ? exception.getStatus() : 500;
    if (status >= 500) this.logger.error(exception);
    // An SSE relay that already started streaming has nothing left to report.
    if (res.headersSent) return void res.end();

    const body = known ? exception.getResponse() : undefined;
    const message = typeof body === 'object' ? (body as { message?: unknown }).message : body;
    res
      .status(status)
      .type('application/problem+json')
      .json({
        type: 'about:blank',
        title: STATUS_CODES[status],
        status,
        // Unknown errors may carry internals; their details stay in the log.
        detail: known ? [message].flat().join('; ') : undefined,
      });
  }
}
