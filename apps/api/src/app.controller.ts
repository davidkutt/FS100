import { Controller, Get } from '@nestjs/common';
import { AppService, type Hello } from './app.service.js';

@Controller()
export class AppController {
  constructor(private readonly appService: AppService) {}

  @Get('hello')
  getHello(): Hello {
    return this.appService.getHello();
  }
}
