import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

@Component({
  selector: 'app-alerts-pager',
  templateUrl: './alerts-pager.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AlertsPager {
  readonly page = input.required<number>();
  readonly totalPages = input.required<number>();
  readonly pageChanged = output<number>();
}
