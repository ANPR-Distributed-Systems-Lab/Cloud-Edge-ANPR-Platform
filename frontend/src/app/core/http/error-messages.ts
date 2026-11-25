import { HttpErrorResponse } from '@angular/common/http';

/** Network errors, 401/403 and 5xx: the interceptor shows them, screens only react to the state. */
export function isHandledGlobally(error: HttpErrorResponse): boolean {
  return error.status === 0 || error.status === 401 || error.status === 403 || error.status >= 500;
}

/** The message of an error the interceptor shows: one that isHandledGlobally. */
export function errorMessage(error: HttpErrorResponse): string {
  if (error.status === 0) {
    return 'Cannot reach the server. Please check your internet connection.';
  }
  if (error.status === 401) {
    return 'Your session has expired. Please sign in again.';
  }
  if (error.status === 403) {
    return 'You are not allowed to do this.';
  }
  // 5xx: the request id finds the request in CloudWatch.
  const requestId: string | undefined =
    error.error?.requestId ?? error.headers?.get('X-Trace-Id') ?? undefined;
  return 'Something went wrong on our side.' + (requestId ? ` Request id: ${requestId}` : '');
}
