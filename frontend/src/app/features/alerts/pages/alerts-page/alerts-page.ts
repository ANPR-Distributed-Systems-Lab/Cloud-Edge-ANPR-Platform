import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, OnInit, inject, signal, viewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { EMPTY, Subject, catchError, exhaustMap, finalize, tap } from 'rxjs';
import { AlertResponse, CreateAlertRequest } from '../../../../api/generated';
import { errorMessage } from '../../../../core/http/error-messages';
import { NotificationService } from '../../../../core/notification.service';
import { AlertForm } from '../../components/alert-form/alert-form';
import { AlertsTable } from '../../components/alerts-table/alerts-table';
import { AlertsFacade } from '../../data-access/alerts.facade';

@Component({
  selector: 'app-alerts-page',
  imports: [AlertForm, AlertsTable],
  templateUrl: './alerts-page.html',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class AlertsPage implements OnInit {
  protected readonly alerts = inject(AlertsFacade);
  private readonly notifications = inject(NotificationService);

  protected readonly saving = signal(false);
  protected readonly editing = signal<AlertResponse | null>(null);

  private readonly form = viewChild.required(AlertForm);
  private readonly saveRequests = new Subject<CreateAlertRequest>();

  constructor() {
    this.saveRequests
      .pipe(
        exhaustMap(request => {
          const current = this.editing();
          this.saving.set(true);
          const save$ = current
            ? this.alerts.update(current.alertId, { ...request, version: current.version })
            : this.alerts.create(request);
          return save$.pipe(
            tap(() => this.closeForm()),
            catchError(error => {
              if (current) {
                this.handleUpdateError(current, error);
              }
              return EMPTY; // create errors are shown by the global error interceptor
            }),
            finalize(() => this.saving.set(false))
          );
        }),
        takeUntilDestroyed()
      )
      .subscribe();
  }

  ngOnInit(): void {
    this.alerts.load().subscribe();
  }

  protected save(request: CreateAlertRequest): void {
    this.saveRequests.next(request);
  }

  protected edit(alert: AlertResponse): void {
    this.editing.set(alert);
  }

  protected closeForm(): void {
    this.editing.set(null);
    this.form().reset();
  }

  protected remove(alertId: string): void {
    this.alerts.delete(alertId).subscribe();
  }

  private handleUpdateError(current: AlertResponse, error: unknown): void {
    if (!(error instanceof HttpErrorResponse)) {
      return;
    }
    const code: string | undefined = error.error?.code;

    if (code === 'CONCURRENT_MODIFICATION') {
      this.alerts.get(current.alertId).subscribe(fresh => {
        this.editing.set(fresh);
        this.notifications.error('Someone else changed this alert. The latest version has been loaded.');
      });
      return;
    }
    if (error.status === 404) {
      this.closeForm();
      this.alerts.load().subscribe();
    }
    this.notifications.error(errorMessage(error));
  }
}