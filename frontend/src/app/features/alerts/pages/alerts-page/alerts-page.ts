import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, inject, signal, viewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { EMPTY, Subject, catchError, exhaustMap, finalize, tap } from 'rxjs';
import { AlertsFacade } from '../../data-access/alerts.facade';
import { AlertsTable } from '../../components/alerts-table/alerts-table';
import { AlertForm } from '../../components/alert-form/alert-form';
import { CreateAlertRequest } from '../../../../api/generated';

const PLATE_PATTERN = /^[A-Z0-9]{2,10}$/;

@Component({
  selector: 'app-alerts-page',
  imports: [AlertForm, AlertsTable],
  templateUrl: './alerts-page.html',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class AlertsPage implements OnInit {
  protected readonly alerts = inject(AlertsFacade);
  protected readonly saving = signal(false);
  protected readonly form = viewChild(AlertForm);
  private readonly addRequests = new Subject<CreateAlertRequest>();

  

  constructor() {
    this.addRequests.pipe(
      exhaustMap(request => {
        this.saving.set(true);
        return this.alerts.create(request).pipe(
          catchError(() => EMPTY),
          finalize(() => this.saving.set(false))
        );
      }),
      takeUntilDestroyed()
    ).subscribe();
  }

  ngOnInit(): void {
    this.alerts.load().subscribe();
  }

  protected add(request: CreateAlertRequest): void {
    this.addRequests.next(request);
  }

  protected remove(alertId: string): void {
    this.alerts.delete(alertId).subscribe();
  }
}