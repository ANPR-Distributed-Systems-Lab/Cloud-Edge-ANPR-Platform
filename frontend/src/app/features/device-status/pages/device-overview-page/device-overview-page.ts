import { DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { DeviceResponse, DeviceService } from '../../../../api/generated/device-management';
import { isHandledGlobally } from '../../../../core/http/error-messages';
import { NotificationService } from '../../../../core/notification.service';

/** View 5 (device status): the device of the account, online or not (GET /api/v1/device). */
@Component({
  selector: 'app-device-overview-page',
  imports: [DatePipe],
  templateUrl: './device-overview-page.html',
  styleUrl: './device-overview-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DeviceOverviewPage {
  private readonly deviceService = inject(DeviceService);
  private readonly notifications = inject(NotificationService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly device = signal<DeviceResponse | null>(null);
  protected readonly loading = signal(true);
  protected readonly error = signal<string | null>(null);

  constructor() {
    this.load();
  }

  protected load(): void {
    this.notifications.clear();
    this.loading.set(true);
    this.error.set(null);

    this.deviceService
      .getDevice()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (device) => {
          this.device.set(device);
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
            this.error.set('The device could not be loaded.');
          }
          this.loading.set(false);
        },
      });
  }
}
