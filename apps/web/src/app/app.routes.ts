import { Routes } from '@angular/router';
import { roleGuard } from './core/role.guard';

export const routes: Routes = [
  {
    path: '',
    title: 'FS100',
    loadComponent: () => import('./features/home/home').then((m) => m.Home),
  },
  {
    path: 'chat',
    title: 'Chat · FS100',
    canActivate: [roleGuard],
    data: { role: 'viewer' },
    loadComponent: () => import('./features/chat/chat').then((m) => m.Chat),
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
  { path: '**', redirectTo: '' },
];
