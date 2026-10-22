import { Routes } from '@angular/router';

export const routes: Routes = [
    { path: '', redirectTo: 'alerts', pathMatch: 'full'},
    {
        path: 'alerts',
        loadComponent: () => import('./features/alerts/alerts-page').then(m => m.AlertsPage)
    }
];
