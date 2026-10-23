import { Component, inject } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import Keycloak from 'keycloak-js';

@Component({
  selector: 'app-root',
  imports: [RouterLink, RouterLinkActive, RouterOutlet],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App {
  protected readonly keycloak = inject(Keycloak);
  protected readonly links = [
    { path: '/', label: 'Home' },
    { path: '/chat', label: 'Chat' },
    { path: '/documents', label: 'Documents' },
    { path: '/inspector', label: 'Inspector' },
    ...(this.keycloak.hasRealmRole('admin')
      ? [
          { path: '/admin/audit', label: 'Audit log' },
          { path: '/admin/usage', label: 'Usage' },
        ]
      : []),
  ];
}
