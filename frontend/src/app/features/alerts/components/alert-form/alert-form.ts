import { ChangeDetectionStrategy, Component, effect, input, output } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { AlertResponse, CreateAlertRequest } from '../../../../api/generated';   

const PLATE_PATTERN = /^[A-Z0-9]{2,10}$/;
@Component({
    selector: 'app-alert-form',
    imports: [ReactiveFormsModule],
    templateUrl: './alert-form.html',
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class AlertForm {
    readonly saving = input(false);
    readonly alert = input<AlertResponse | null>(null);
    readonly submitted = output<CreateAlertRequest>();
    readonly cancelled = output<void>();

    protected readonly form = new FormGroup({
        plate: new FormControl('', { nonNullable: true, validators: [Validators.required, Validators.pattern(PLATE_PATTERN)] }),
        alertText: new FormControl('', { nonNullable: true, validators: [Validators.maxLength(500)] })
    });

    constructor() {
        effect(() => {
        const alert = this.alert();
        if (alert) {
            this.form.setValue({ plate: alert.plate, alertText: alert.alertText ?? '' });
        }
        });
    }

    reset(): void {
        this.form.reset();
    }

    protected normalizePlate(): void {
        const control = this.form.controls.plate;
        control.setValue(control.value.toUpperCase().replace(/[^A-Z0-9]/g, ''));
    }

    protected submit(): void {
        if (this.form.invalid){
            this.form.markAllAsTouched();
            return;
        }

        const { plate, alertText } = this.form.getRawValue();
        this.submitted.emit({ plate, alertText: alertText || undefined })
    }

    protected cancel(): void {
        this.form.reset();
        this.cancelled.emit();
    }
}