import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, throwError } from 'rxjs';
import { NotificationService } from './notification.service';
import { SKIP_GLOBAL_ERROR } from './http/error-context';
import { errorMessage } from './http/error-messages';

export const errorInterceptor: HttpInterceptorFn = (req, next) => {
    const notificationService = inject(NotificationService);

    return next(req).pipe(
        catchError((error: unknown) => {
            if (error instanceof HttpErrorResponse && !req.context.get(SKIP_GLOBAL_ERROR)) {
                notificationService.error(errorMessage(error));
            }
            return throwError(() => error);
        })
    );
}
        