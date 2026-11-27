import { ApplicationConfig, isDevMode, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { provideRouter } from '@angular/router';

import { routes } from './app.routes';
import { provideApi } from './api/generated/device-management';
import { devAccountInterceptor } from './core/dev-account.interceptor';
import { errorInterceptor } from './core/error.interceptor';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(routes),
    provideHttpClient(
      withInterceptors([...(isDevMode() ? [devAccountInterceptor] : []), errorInterceptor]),
    ),
    // Same origin: the dev server proxies /api (proxy.conf.json), API Gateway serves it in AWS.
    provideApi(''),
  ],
};
