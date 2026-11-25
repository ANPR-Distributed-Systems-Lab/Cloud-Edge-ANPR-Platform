import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, provideRouter } from '@angular/router';
import {
  DeviceConfigurationResponse,
  ExposureConfigurationModeEnum,
  provideApi,
  WhiteBalanceConfigurationModeEnum,
} from '../../../../api/generated/device-management';
import { errorInterceptor } from '../../../../core/error.interceptor';
import { NotificationService } from '../../../../core/notification.service';
import { ConfigSection } from '../../components/device-config-form/device-config-form';
import { DeviceConfigPage } from './device-config-page';

const URL = '/api/v1/device/config';

const CONFIG: DeviceConfigurationResponse = {
  deviceId: 'b352e6fb-0000-4000-8000-000000000001',
  version: 7,
  updatedAt: '2026-11-24T15:16:03Z',
  plateCooldownSeconds: 30,
  batching: {
    detectionsBatchSize: 20,
    locationsBatchSize: 50,
    imageUrlsBatchSize: 10,
    imageUploadsLowPriority: true,
    maxBatchDelaySeconds: 10,
  },
  ml: {
    detectorMinConfidence: 0.5,
    ocrMinConfidence: 0.6,
    readableMinProbability: 0.7,
    minPlateWidthPx: 60,
    minEdgeMarginPx: 8,
  },
  models: { detector: 'v3', ocr: 'v3' },
  intervals: {
    metricsSeconds: 60,
    configPollSeconds: 60,
    alertsPollSeconds: 30,
    locationSampleSeconds: 5,
  },
  gps: { maxFixAgeSeconds: 10 },
  photos: { widthPx: 1280, jpegQuality: 85, maxWaitingFrames: 4, maxStored: 500 },
  camera: {
    fps: 10,
    hflip: false,
    vflip: true,
    exposure: {
      mode: ExposureConfigurationModeEnum.Auto,
      exposureUs: 10000,
      gain: 2,
      maxExposureUs: 20000,
      maxGain: 8,
      targetBrightness: 0.5,
      meteringTop: 0.3,
      meteringBottom: 0.9,
    },
    whiteBalance: { mode: WhiteBalanceConfigurationModeEnum.Auto, redGain: 1.5, blueGain: 1.5 },
  },
};

/** What the page sends for CONFIG: the version and every setting, without the read-only fields. */
const { deviceId: _deviceId, updatedAt: _updatedAt, ...UNCHANGED_REQUEST } = CONFIG;

function problem(status: number, code: string, extra: object = {}) {
  return { type: 'about:blank', title: 'x', status, code, requestId: 'req-1', ...extra };
}

describe('DeviceConfigPage', () => {
  let fixture: ComponentFixture<DeviceConfigPage>;
  let http: HttpTestingController;
  let notifications: NotificationService;

  async function create(section: ConfigSection = 'reading'): Promise<void> {
    TestBed.configureTestingModule({
      imports: [DeviceConfigPage],
      providers: [
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideApi(''),
        provideRouter([]),
        { provide: ActivatedRoute, useValue: { snapshot: { data: { section } } } },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    notifications = TestBed.inject(NotificationService);
    fixture = TestBed.createComponent(DeviceConfigPage);
    await render();
  }

  async function render(): Promise<void> {
    await fixture.whenStable();
    fixture.detectChanges();
  }

  async function loaded(section: ConfigSection = 'reading', config = CONFIG): Promise<void> {
    await create(section);
    http.expectOne({ method: 'GET', url: URL }).flush(config);
    await render();
  }

  function el<T extends HTMLElement>(selector: string): T | null {
    return fixture.nativeElement.querySelector(selector);
  }

  function text(): string {
    return fixture.nativeElement.textContent;
  }

  function button(label: string): HTMLButtonElement {
    const found = [...fixture.nativeElement.querySelectorAll('button')].find(
      (b: HTMLButtonElement) => b.textContent?.includes(label),
    );
    if (!found) {
      throw new Error(`No button "${label}"`);
    }
    return found;
  }

  async function type(selector: string, value: string): Promise<void> {
    const input = el<HTMLInputElement>(selector)!;
    input.value = value;
    input.dispatchEvent(new Event('input'));
    await render();
  }

  async function clickSave(): Promise<void> {
    button('Save').click();
    await render();
  }

  async function failSave(status: number, code: string, extra: object = {}): Promise<void> {
    http
      .expectOne({ method: 'PUT', url: URL })
      .flush(problem(status, code, extra), { status, statusText: 'x' });
    await render();
  }

  afterEach(() => http.verify());

  describe('reading', () => {
    it('fills the fields of its section with the configuration', async () => {
      await loaded('reading');

      expect(el<HTMLInputElement>('#plate-cooldown')!.value).toBe('30');
      expect(el<HTMLInputElement>('#ml-detector')!.value).toBe('0.5');
    });

    it('shows only the fields of its section', async () => {
      await loaded('models');

      expect(el('#models-detector')).not.toBeNull();
      expect(el('#camera-fps')).toBeNull();
      expect(el('#plate-cooldown')).toBeNull();
    });

    it('tells that the account has no device, without a notice', async () => {
      await create();
      http
        .expectOne(URL)
        .flush(problem(404, 'DEVICE_NOT_FOUND'), { status: 404, statusText: 'Not Found' });
      await render();

      expect(text()).toContain('This account has no device yet');
      expect(el('form')).toBeNull();
      expect(notifications.notice()).toBeNull();
    });

    it('shows a server error once, with its request id', async () => {
      await create();
      const error = vi.spyOn(notifications, 'error');
      http.expectOne(URL).flush(problem(500, 'INTERNAL_ERROR'), { status: 500, statusText: 'x' });
      await render();

      expect(error).toHaveBeenCalledTimes(1);
      expect(notifications.notice()?.text).toContain('req-1');
      expect(text()).not.toContain('could not be loaded');
      expect(button('Try again')).toBeTruthy();
    });

    it('loads again after "Try again"', async () => {
      await create();
      http.expectOne(URL).flush(problem(500, 'INTERNAL_ERROR'), { status: 500, statusText: 'x' });
      await render();

      button('Try again').click();
      await render();
      http.expectOne({ method: 'GET', url: URL }).flush(CONFIG);
      await render();

      expect(el('form')).not.toBeNull();
      expect(notifications.notice()).toBeNull(); // the old error is gone
    });
  });

  describe('saving', () => {
    it('sends the version it read and every section, also those it does not show', async () => {
      await loaded('models');

      await clickSave();

      const put = http.expectOne({ method: 'PUT', url: URL });
      expect(put.request.body).toEqual(UNCHANGED_REQUEST);
      put.flush(CONFIG);
    });

    it('sends a changed value', async () => {
      await loaded('reading');

      await type('#plate-cooldown', '99');
      await clickSave();

      const put = http.expectOne({ method: 'PUT', url: URL });
      expect(put.request.body).toEqual({ ...UNCHANGED_REQUEST, plateCooldownSeconds: 99 });
      put.flush(CONFIG);
    });

    it('confirms the save and sends the new version next time', async () => {
      await loaded();

      await clickSave();
      http.expectOne({ method: 'PUT', url: URL }).flush({ ...CONFIG, version: 8 });
      await render();
      expect(notifications.notice()).toEqual({
        kind: 'success',
        text: 'Configuration saved. The device applies it at its next check.',
      });

      await clickSave();
      const second = http.expectOne({ method: 'PUT', url: URL });
      expect(second.request.body.version).toBe(8);
      second.flush({ ...CONFIG, version: 9 });
    });

    it('disables the button while saving', async () => {
      await loaded();

      await clickSave();
      expect(button('Saving').disabled).toBe(true);

      http.expectOne({ method: 'PUT', url: URL }).flush(CONFIG);
      await render();
      expect(button('Save Changes').disabled).toBe(false);
    });

    it('keeps the typed values and offers a reload when someone else saved first', async () => {
      await loaded();
      await type('#plate-cooldown', '99');

      await clickSave();
      await failSave(409, 'CONCURRENT_MODIFICATION');

      expect(text()).toContain('Someone else saved this configuration');
      expect(notifications.notice()).toBeNull(); // the page shows the conflict, once
      expect(el<HTMLInputElement>('#plate-cooldown')!.value).toBe('99');
    });

    it('loads the current configuration from the conflict message', async () => {
      await loaded();
      await clickSave();
      await failSave(409, 'CONCURRENT_MODIFICATION');

      button('Load the current configuration').click();
      await render();
      http
        .expectOne({ method: 'GET', url: URL })
        .flush({ ...CONFIG, version: 9, plateCooldownSeconds: 45 });
      await render();

      expect(text()).not.toContain('Someone else saved this configuration');
      expect(el<HTMLInputElement>('#plate-cooldown')!.value).toBe('45');
    });

    it('shows a server error once, with its request id', async () => {
      await loaded();
      const error = vi.spyOn(notifications, 'error');

      await clickSave();
      await failSave(500, 'INTERNAL_ERROR');

      expect(error).toHaveBeenCalledTimes(1);
      expect(notifications.notice()?.text).toContain('req-1');
      expect(el('.message')).toBeNull();
    });

    it('falls back to the generic message for an unknown code', async () => {
      await loaded();

      await clickSave();
      await failSave(422, 'SOMETHING_NEW');

      expect(el('.message')!.textContent).toContain('The configuration could not be saved.');
      expect(notifications.notice()).toBeNull();
    });

    it('removes the notice of an earlier save when the next one fails', async () => {
      await loaded();
      await clickSave();
      http.expectOne({ method: 'PUT', url: URL }).flush({ ...CONFIG, version: 8 });
      await render();

      await clickSave();
      await failSave(400, 'VALIDATION_FAILED', { fields: [] });

      expect(notifications.notice()).toBeNull();
    });
  });

  describe('field errors', () => {
    const NOT_PUBLISHED = {
      field: 'models.detector',
      code: 'MODEL_NOT_PUBLISHED',
      message: 'Version v9 is not published',
    };

    function invalid(id: string): string | null {
      return el(`#${id}`)!.getAttribute('aria-invalid');
    }

    function message(id: string): string {
      return el(`#${id}-error`)!.textContent!.trim();
    }

    async function leave(id: string): Promise<void> {
      el(`#${id}`)!.dispatchEvent(new Event('blur'));
      await render();
    }

    it('marks a field the server refused, with a message chosen by its code', async () => {
      await loaded('models');

      await clickSave();
      await failSave(400, 'VALIDATION_FAILED', { fields: [NOT_PUBLISHED] });

      expect(invalid('models-detector')).toBe('true');
      expect(message('models-detector')).toBe('This version is not published.');
      expect(text()).not.toContain('Version v9 is not published'); // the server text is not shown
      expect(invalid('models-ocr')).toBe('false');
      expect(el('.message')).toBeNull(); // the field is on this page, so no list above the form
      expect(notifications.notice()).toBeNull();
    });

    it('drops the mark of the server once the field is edited', async () => {
      await loaded('models');
      await clickSave();
      await failSave(400, 'VALIDATION_FAILED', { fields: [NOT_PUBLISHED] });

      await type('#models-detector', 'v4');

      expect(invalid('models-detector')).toBe('false');
      expect(message('models-detector')).toBe('');
    });

    it('sends a refused value again: only the server knows whether it is fine now', async () => {
      await loaded('models');
      await clickSave();
      await failSave(400, 'VALIDATION_FAILED', { fields: [NOT_PUBLISHED] });

      await clickSave();

      http.expectOne({ method: 'PUT', url: URL }).flush(CONFIG);
    });

    it('lists refused fields of other sections with a link to them', async () => {
      await loaded('reading');

      await clickSave();
      await failSave(400, 'VALIDATION_FAILED', { fields: [NOT_PUBLISHED] });

      const box = el('.message')!;
      expect(box.textContent).toContain('This version is not published.');
      expect(box.querySelector('a')!.getAttribute('href')).toBe('/config/models');
    });

    it('explains the metered band the server refused', async () => {
      await loaded('camera');
      await clickSave();
      const band = { field: 'camera.exposure.meteringBottom', code: 'RANGE' };
      await failSave(400, 'VALIDATION_FAILED', { fields: [band] });

      expect(message('exposure-bottom')).toBe('Must be greater than the top of the band.');
    });

    it('does not send a value outside the limits of the contract', async () => {
      await loaded('reading');

      await type('#plate-cooldown', '5000');
      await clickSave();

      http.expectNone({ method: 'PUT', url: URL });
      expect(invalid('plate-cooldown')).toBe('true');
      expect(message('plate-cooldown')).toBe('Must be at most 3600.');
    });

    it('shows the message only once the person leaves the field', async () => {
      await loaded('reading');

      await type('#ml-width', '5');
      expect(message('ml-width')).toBe('');

      await leave('ml-width');
      expect(message('ml-width')).toBe('Must be at least 10.');
    });

    it('asks for a whole number where the contract has an integer', async () => {
      await loaded('reading');

      await type('#plate-cooldown', '1.5');
      await leave('plate-cooldown');

      expect(message('plate-cooldown')).toBe('Enter a whole number.');
    });

    it('asks for a value in an empty field', async () => {
      await loaded('camera');

      await type('#exposure-gain', '');
      await leave('exposure-gain');

      expect(message('exposure-gain')).toBe('Enter a value.');
    });

    it('checks the format of a model version', async () => {
      await loaded('models');

      await type('#models-ocr', 'v 9');
      await clickSave();

      http.expectNone({ method: 'PUT', url: URL });
      expect(message('models-ocr')).toBe(
        'Use letters, digits, ".", "_" or "-", up to 64 characters.',
      );
    });
  });
});
