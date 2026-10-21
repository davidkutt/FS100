import { Routes } from '@angular/router';
import { roleGuard } from './core/role.guard';

export const routes: Routes = [
  {
    path: '',
    title: 'FS100',
    loadComponent: () => import('./features/home/home').then((m) => m.Home),
  },
  {
    // One route for `chat` and `chat/:id`, so the page survives starting a conversation.
    matcher: (url) =>
      url[0]?.path === 'chat' && url.length <= 2
        ? { consumed: url, posParams: url[1] ? { id: url[1] } : undefined }
        : null,
    title: 'Chat · FS100',
    canActivate: [roleGuard],
    data: { role: 'viewer' },
    loadComponent: () =>
      import('./features/conversations/conversations').then((m) => m.Conversations),
  },
  {
    path: 'documents',
    title: 'Documents · FS100',
    canActivate: [roleGuard],
    data: { role: 'viewer' },
    loadComponent: () => import('./features/documents/documents').then((m) => m.Documents),
  },
  {
    path: 'inspector',
    title: 'Retrieval inspector · FS100',
    canActivate: [roleGuard],
    data: { role: 'viewer' },
    loadComponent: () => import('./features/inspector/inspector').then((m) => m.Inspector),
  },
  {
    path: 'admin/audit',
    title: 'Audit log · FS100',
    canActivate: [roleGuard],
    data: { role: 'admin' },
    loadComponent: () => import('./features/admin/audit').then((m) => m.Audit),
  },
  { path: '**', redirectTo: '' },
];
