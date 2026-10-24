import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { EMPTY, Subject, catchError, exhaustMap, finalize, tap } from 'rxjs';
import { AlertsFacade } from '../../data-access/alerts.facade';

const PLATE_PATTERN = /^[A-Z0-9]{2,10}$/;

@Component({
  selector: 'app-alerts-page',
  imports: [DatePipe, ReactiveFormsModule],
  templateUrl: './alerts-page.html',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class AlertsPage implements OnInit {
  protected readonly alerts = inject(AlertsFacade);
  protected readonly saving = signal(false);

  private readonly addClicks = new Subject<void>();

  protected readonly form = new FormGroup({
    plate: new FormControl('', {
      nonNullable: true,
      validators: [Validators.required, Validators.pattern(PLATE_PATTERN)]
    }),
    alertText: new FormControl('', {
      nonNullable: true,
      validators: [Validators.maxLength(500)]
    })
  });

  constructor() {
    this.addClicks
      .pipe(
        exhaustMap(() => {
          const { plate, alertText } = this.form.getRawValue();
          this.saving.set(true);
          return this.alerts.create({ plate, alertText: alertText || undefined }).pipe(
            tap(() => this.form.reset()),
            catchError(() => EMPTY), // message shown by the global error interceptor; keep the stream alive
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

  protected normalizePlate(): void {
    const control = this.form.controls.plate;
    control.setValue(control.value.toUpperCase().replace(/\s/g, ''));
  }

  protected add(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    this.addClicks.next();
  }

  protected remove(alertId: string): void {
    this.alerts.delete(alertId).subscribe();
  }
}