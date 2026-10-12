import { Injectable } from '@nestjs/common';

export interface Hello {
  message: string;
}

@Injectable()
export class AppService {
  getHello(): Hello {
    return { message: 'Hello from the FS100 API' };
  }
}
