import {
  HttpClient,
  HttpErrorResponse,
  provideHttpClient,
  withInterceptors,
} from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { errorInterceptor } from './error.interceptor';
import { NotificationService } from './notification.service';

describe('errorInterceptor', () => {
  let client: HttpClient;
  let http: HttpTestingController;
  let notifications: NotificationService;
  /** What reached the caller: the interceptor must always pass the error on. */
  let received: HttpErrorResponse | undefined;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
      ],
    });
    client = TestBed.inject(HttpClient);
    http = TestBed.inject(HttpTestingController);
    notifications = TestBed.inject(NotificationService);
    received = undefined;
    client.get('/api/x').subscribe({ error: (error: HttpErrorResponse) => (received = error) });
  });

  afterEach(() => http.verify());

  function answer(status: number, body: object = {}, headers: Record<string, string> = {}): void {
    http.expectOne('/api/x').flush(body, { status, statusText: 'x', headers });
  }

  it('tells about a lost connection', () => {
    http.expectOne('/api/x').error(new ProgressEvent('error'));

    expect(notifications.notice()?.text).toBe(
      'Cannot reach the server. Please check your internet connection.',
    );
    expect(received?.status).toBe(0);
  });

  it('tells that the session expired on 401', () => {
    answer(401);

    expect(notifications.notice()?.text).toBe('Your session has expired. Please sign in again.');
  });

  it('tells that the action is not allowed on 403', () => {
    answer(403, { code: 'FORBIDDEN' });

    expect(notifications.notice()?.text).toBe('You are not allowed to do this.');
  });

  it('takes the request id of a 5xx from X-Trace-Id when the body has none', () => {
    answer(503, {}, { 'X-Trace-Id': 'trace-9' });

    expect(notifications.notice()?.text).toBe(
      'Something went wrong on our side. Request id: trace-9',
    );
  });

  it.each([400, 404, 409])('leaves a %i to the screen', (status) => {
    answer(status, { code: 'ANY' });

    expect(notifications.notice()).toBeNull();
    expect(received?.status).toBe(status);
  });

  it('passes a handled error on to the caller', () => {
    answer(500, { code: 'INTERNAL_ERROR', requestId: 'req-1' });

    expect(notifications.notice()?.text).toContain('req-1');
    expect(received?.status).toBe(500);
  });
});
