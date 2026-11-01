import { HttpErrorResponse } from '@angular/common/http';

const BY_CODE: Record<string, string> = {
  ALERT_ALREADY_EXISTS: 'An alert for this plate already exists.',
  ALERT_NOT_FOUND: 'This alert no longer exists.',
  CONCURRENT_MODIFICATION: 'Someone else changed this alert. Refresh and try again.',
  VALIDATION_FAILED: 'Some fields are invalid.',
  INVALID_REQUEST: 'The request was invalid.',
  UNAUTHENTICATED: 'Your session has expired. Please sign in again.'
};

export function errorMessage(error: HttpErrorResponse): string {
    if (error.status === 0) {
        return 'Cannot reach the server. Please check your internet connection.';
    }

    const code: string | undefined = error.error?.code;

    return (code && BY_CODE[code]) ?? 'Something went wrong. Please try again.';
}