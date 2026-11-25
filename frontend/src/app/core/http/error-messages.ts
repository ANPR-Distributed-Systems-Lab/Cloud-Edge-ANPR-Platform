import { HttpErrorResponse } from '@angular/common/http';

const BY_CODE: Record<string, string> = {
  DEVICE_NOT_FOUND: 'This account has no device.',
  CONCURRENT_MODIFICATION: 'Someone else changed this in the meantime.',
  VALIDATION_FAILED: 'Some fields are invalid.',
  INVALID_REQUEST: 'The request was invalid.',
  FORBIDDEN: 'You are not allowed to do this.',
};

/** Network errors, 401/403 and 5xx: the interceptor shows them, screens only react to the state. */
export function isHandledGlobally(error: HttpErrorResponse): boolean {
  return error.status === 0 || error.status === 401 || error.status === 403 || error.status >= 500;
}

/** The code of the problem: the only part of an error body the UI relies on (messages change). */
export function errorCode(error: HttpErrorResponse): string | undefined {
  return error.error?.code;
}

export function errorMessage(error: HttpErrorResponse): string {
  if (error.status === 0) {
    return 'Cannot reach the server. Please check your internet connection.';
  }
  if (error.status === 401) {
    return 'Your session has expired. Please sign in again.';
  }
  if (error.status >= 500) {
    // The request id finds the request in CloudWatch.
    const requestId: string | undefined =
      error.error?.requestId ?? error.headers?.get('X-Trace-Id') ?? undefined;
    return 'Something went wrong on our side.' + (requestId ? ` Request id: ${requestId}` : '');
  }
  const code = errorCode(error);
  return (code && BY_CODE[code]) ?? 'Something went wrong. Please try again.';
}
