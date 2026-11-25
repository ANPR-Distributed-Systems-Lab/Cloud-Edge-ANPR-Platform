import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, throwError } from 'rxjs';
import { NotificationService } from './notification.service';
import { errorMessage, isHandledGlobally } from './http/error-messages';

/**
 * Shows the message of errors no screen can act on (network, 401/403, 5xx) and always rethrows.
 * Business errors (other 4xx) are left to the screen, so one error never gets two messages.
 */
export const errorInterceptor: HttpInterceptorFn = (req, next) => {
  const notifications = inject(NotificationService);

  return next(req).pipe(
    catchError((error: unknown) => {
      if (error instanceof HttpErrorResponse && isHandledGlobally(error)) {
        notifications.error(errorMessage(error));
      }
      return throwError(() => error);
    }),
  );
};
