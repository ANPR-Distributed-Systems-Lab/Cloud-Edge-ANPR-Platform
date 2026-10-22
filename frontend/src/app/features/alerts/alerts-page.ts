import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, inject } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { AlertsStore } from './alerts.store';

const PLATE_PATTERN = /^[A-Z0-9]{2,10}$/;

@Component({
  selector: 'app-alerts-page',
  imports: [DatePipe, ReactiveFormsModule],
  templateUrl: './alerts-page.html',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class AlertsPage implements OnInit {
  protected readonly store = inject(AlertsStore);

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

  ngOnInit(): void {
    this.store.load();
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
    const { plate, alertText } = this.form.getRawValue();
    this.store.create(plate, alertText || undefined);
    this.form.reset();
  }

    protected remove(alertId: string): void {
      this.store.delete(alertId);
    }
}