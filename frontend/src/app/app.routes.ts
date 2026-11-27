import { Routes } from '@angular/router';

const overviewPage = () =>
  import('./features/device-status/pages/device-overview-page/device-overview-page').then(
    (m) => m.DeviceOverviewPage,
  );

/**
 * One page for every section of the configuration; data.section says which part of the form it
 * shows.
 */
const configPage = () =>
  import('./features/devices/pages/device-config-page/device-config-page').then(
    (m) => m.DeviceConfigPage,
  );

export const routes: Routes = [
  { path: '', redirectTo: 'device', pathMatch: 'full' },
  { path: 'device', loadComponent: overviewPage },
  { path: 'config', redirectTo: 'config/models', pathMatch: 'full' },
  { path: 'config/models', loadComponent: configPage, data: { section: 'models' } },
  { path: 'config/reading', loadComponent: configPage, data: { section: 'reading' } },
  { path: 'config/intervals', loadComponent: configPage, data: { section: 'intervals' } },
  { path: 'config/sending', loadComponent: configPage, data: { section: 'sending' } },
  { path: 'config/photos', loadComponent: configPage, data: { section: 'photos' } },
  { path: 'config/camera', loadComponent: configPage, data: { section: 'camera' } },
  { path: '**', redirectTo: 'device' },
];
