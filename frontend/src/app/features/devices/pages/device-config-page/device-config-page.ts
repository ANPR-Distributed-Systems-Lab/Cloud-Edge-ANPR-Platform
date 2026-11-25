import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  DestroyRef,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import {
  ConfigurationService,
  DeviceConfigurationResponse,
  FieldError,
  UpdateDeviceConfigurationRequest,
} from '../../../../api/generated/device-management';
import { isHandledGlobally } from '../../../../core/http/error-messages';
import { NotificationService } from '../../../../core/notification.service';
import {
  ConfigSection,
  DeviceConfigForm,
  sectionOf,
  serverMessage,
} from '../../components/device-config-form/device-config-form';

const TITLES: Record<ConfigSection, string> = {
  models: 'Models',
  reading: 'Reading plates',
  intervals: 'Intervals',
  sending: 'Sending',
  photos: 'Photos',
  camera: 'Camera',
};

/**
 * View 4: one section of the device configuration (GET and PUT /api/v1/device/config).
 * The route says which section (data.section). The whole configuration is loaded and saved; the
 * page only shows one part.
 */
@Component({
  selector: 'app-device-config-page',
  imports: [DeviceConfigForm, RouterLink],
  templateUrl: './device-config-page.html',
  styleUrl: './device-config-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DeviceConfigPage {
  private readonly configurationService = inject(ConfigurationService);
  private readonly notifications = inject(NotificationService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly section: ConfigSection = inject(ActivatedRoute).snapshot.data['section'];
  protected readonly title = TITLES[this.section];

  protected readonly config = signal<DeviceConfigurationResponse | null>(null);
  protected readonly loading = signal(true);
  protected readonly error = signal<string | null>(null);

  protected readonly saving = signal(false);
  protected readonly saveError = signal<string | null>(null);
  /** 409: someone saved after this page read the configuration. */
  protected readonly conflict = signal(false);

  /** 400 VALIDATION_FAILED: the refused fields, shown by the form next to each field. */
  protected readonly fieldErrors = signal<FieldError[]>([]);
  /** Refused fields of other sections: this page has no field to show them at. */
  protected readonly refusedElsewhere = computed(() =>
    this.fieldErrors().filter((error) => sectionOf(error.field) !== this.section),
  );
  protected readonly titles = TITLES;
  protected readonly sectionOf = sectionOf;
  protected readonly serverMessage = serverMessage;

  constructor() {
    this.load();
  }

  protected load(): void {
    this.notifications.clear();
    this.loading.set(true);
    this.error.set(null);
    this.saveError.set(null);
    this.fieldErrors.set([]);
    this.conflict.set(false);

    this.configurationService
      .getDeviceConfiguration()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (config) => {
          this.config.set(config);
          this.loading.set(false);
        },
        error: (error: HttpErrorResponse) => {
          if (error.error?.code === 'DEVICE_NOT_FOUND') {
            this.error.set(
              'This account has no device yet. An administrator pairs a device with the account.',
            );
          } else if (isHandledGlobally(error)) {
            // The error interceptor already shows the message.
            // The page keeps only the retry button.
            this.error.set('');
          } else {
            this.error.set('The configuration could not be loaded.');
          }
          this.loading.set(false);
        },
      });
  }

  protected save(request: UpdateDeviceConfigurationRequest): void {
    // A notice of an earlier save must not stay next to the result of this one.
    this.notifications.clear();
    this.saving.set(true);
    this.saveError.set(null);
    this.fieldErrors.set([]);
    this.conflict.set(false);

    this.configurationService
      .updateDeviceConfiguration(request)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (saved) => {
          // The response carries the new version, which the next save must send.
          this.config.set(saved);
          this.saving.set(false);
          this.notifications.success(
            'Configuration saved. The device applies it at its next check.',
          );
        },
        error: (error: HttpErrorResponse) => {
          this.saving.set(false);
          const code = error.error?.code;
          if (code === 'CONCURRENT_MODIFICATION') {
            this.conflict.set(true);
          } else if (code === 'VALIDATION_FAILED') {
            const fields: FieldError[] = error.error?.fields ?? [];
            this.fieldErrors.set(fields);
            if (fields.length === 0) {
              this.saveError.set('Some values were refused.');
            }
          } else if (!isHandledGlobally(error)) {
            // Network, 401/403 and 5xx are already shown by the error interceptor.
            this.saveError.set('The configuration could not be saved.');
          }
        },
      });
  }
}
