import { ChangeDetectionStrategy, Component, output, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { debounceTime, distinctUntilChanged, filter, map, tap } from 'rxjs';
import { normalizePlate } from '../../../../shared/util/plate';
import { AlertsFilter } from '../../data-access/alerts.store';

@Component({
  selector: 'app-alerts-filter-bar',
  imports: [ReactiveFormsModule],
  templateUrl: './alerts-filter-bar.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AlertsFilterBar {
  readonly filterChanged = output<AlertsFilter>();

  protected readonly form = new FormGroup({
    plate: new FormControl('', { nonNullable: true }),
    from: new FormControl('', { nonNullable: true }),
    to: new FormControl('', { nonNullable: true }),
  });
  protected readonly rangeInvalid = signal(false);

  constructor() {
    this.form.valueChanges
      .pipe(
        map(() => toFilter(this.form.getRawValue())),
        debounceTime(250),
        distinctUntilChanged((a, b) => a.plate === b.plate && a.from === b.from && a.to === b.to),
        tap((value) =>
          this.rangeInvalid.set(value.from !== '' && value.to !== '' && value.from >= value.to),
        ),
        filter(() => !this.rangeInvalid()),
        takeUntilDestroyed(),
      )
      .subscribe((value) => this.filterChanged.emit(value));
  }
}

/**
 * Turns the form's local dates (`yyyy-MM-dd`) into the API's UTC instants. Both days are inclusive for the user,
 * while the API's `to` is exclusive, so `to` becomes the start of the following day.
 */
function toFilter(value: AlertsFilter): AlertsFilter {
  return {
    plate: normalizePlate(value.plate),
    from: value.from === '' ? '' : startOfLocalDay(value.from, 0),
    to: value.to === '' ? '' : startOfLocalDay(value.to, 1),
  };
}

// `new Date('2026-11-01')` would be UTC midnight; adding the time makes it local midnight.
function startOfLocalDay(date: string, plusDays: number): string {
  const day = new Date(`${date}T00:00`);
  day.setDate(day.getDate() + plusDays);
  return day.toISOString();
}
