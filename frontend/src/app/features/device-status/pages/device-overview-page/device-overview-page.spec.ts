import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { DeviceResponse, provideApi } from '../../../../api/generated/device-management';
import { errorInterceptor } from '../../../../core/error.interceptor';
import { NotificationService } from '../../../../core/notification.service';
import { DeviceOverviewPage } from './device-overview-page';

const URL = '/api/v1/device';

const DEVICE: DeviceResponse = {
  deviceId: 'b352e6fb-0000-4000-8000-000000000001',
  username: 'rpi-01',
  createdAt: '2026-11-24T15:16:03Z',
  lastMetricsAt: '2026-11-24T16:40:00Z',
  online: true,
};

function problem(status: number, code: string) {
  return { type: 'about:blank', title: 'x', status, code, requestId: 'req-1' };
}

describe('DeviceOverviewPage', () => {
  let fixture: ComponentFixture<DeviceOverviewPage>;
  let http: HttpTestingController;
  let notifications: NotificationService;

  beforeEach(async () => {
    TestBed.configureTestingModule({
      imports: [DeviceOverviewPage],
      providers: [
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideApi(''),
      ],
    });
    http = TestBed.inject(HttpTestingController);
    notifications = TestBed.inject(NotificationService);
    fixture = TestBed.createComponent(DeviceOverviewPage);
    await render();
  });

  afterEach(() => http.verify());

  async function render(): Promise<void> {
    await fixture.whenStable();
    fixture.detectChanges();
  }

  function text(): string {
    return fixture.nativeElement.textContent;
  }

  it('shows the name, the state and the dates of the device', async () => {
    http.expectOne({ method: 'GET', url: URL }).flush(DEVICE);
    await render();

    expect(text()).toContain('rpi-01');
    expect(text()).toContain('Online');
    expect(text()).toContain('2026'); // both dates are rendered
    expect(text()).not.toContain('never');
  });

  it('says "never" for a device that has not reported yet', async () => {
    http.expectOne(URL).flush({ ...DEVICE, online: false, lastMetricsAt: null });
    await render();

    expect(text()).toContain('Offline');
    expect(text()).toContain('never');
  });

  it('tells that the account has no device, without a notice', async () => {
    http
      .expectOne(URL)
      .flush(problem(404, 'DEVICE_NOT_FOUND'), { status: 404, statusText: 'Not Found' });
    await render();

    expect(text()).toContain('This account has no device yet');
    expect(notifications.notice()).toBeNull();
  });

  it('shows a server error once, with its request id', async () => {
    const error = vi.spyOn(notifications, 'error');
    http.expectOne(URL).flush(problem(500, 'INTERNAL_ERROR'), { status: 500, statusText: 'x' });
    await render();

    expect(error).toHaveBeenCalledTimes(1);
    expect(notifications.notice()?.text).toContain('req-1');
    expect(text()).not.toContain('could not be loaded');
    expect(text()).toContain('Try again');
  });
});
