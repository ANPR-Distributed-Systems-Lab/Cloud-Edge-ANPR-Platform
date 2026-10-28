import { Routes } from '@angular/router';

export const routes: Routes = [
    { path: '', redirectTo: 'alerts', pathMatch: 'full'},
    {
        path: 'alerts',
        loadComponent: () => import('./features/alerts/pages/alerts-page/alerts-page').then(m => m.AlertsPage)
    }
];
