import { Routes } from '@angular/router';

export const routes: Routes = [
  {
    path: '',
    title: 'FS100',
    loadComponent: () => import('./features/home/home').then((m) => m.Home),
  },
  { path: '**', redirectTo: '' },
];
