import {
  ChangeDetectionStrategy,
  Component,
  effect,
  inject,
  input,
  OnInit,
  output,
} from '@angular/core';
import {
  AbstractControl,
  NonNullableFormBuilder,
  ReactiveFormsModule,
  ValidationErrors,
  ValidatorFn,
  Validators,
} from '@angular/forms';
import {
  DeviceConfigurationResponse,
  ExposureConfigurationModeEnum,
  FieldError,
  UpdateDeviceConfigurationRequest,
  WhiteBalanceConfigurationModeEnum,
} from '../../../../api/generated/device-management';

/** The parts of the configuration, one page each in the side menu. */
export type ConfigSection = 'models' | 'reading' | 'intervals' | 'sending' | 'photos' | 'camera';

/** The page that shows a field of the configuration, e.g. 'camera.exposure.gain' → 'camera'. */
export function sectionOf(field: string): ConfigSection | null {
  switch (field.split('.')[0]) {
    case 'models':
      return 'models';
    case 'ml':
    case 'plateCooldownSeconds':
      return 'reading';
    case 'intervals':
    case 'gps':
      return 'intervals';
    case 'batching':
      return 'sending';
    case 'photos':
      return 'photos';
    case 'camera':
      return 'camera';
    default:
      return null;
  }
}

/** The message for a field the server refused, chosen by its code (the server text may change). */
export function serverMessage(error: FieldError): string {
  switch (error.code) {
    case 'MODEL_NOT_PUBLISHED':
      return 'This version is not published.';
    case 'RANGE':
      // The only range the form cannot check alone: the band needs both of its edges.
      return error.field === 'camera.exposure.meteringBottom'
        ? 'Must be greater than the top of the band.'
        : 'Outside the allowed range.';
    case 'REQUIRED':
      return 'Enter a value.';
    default:
      return 'The server refused this value.';
  }
}

/** The versions the server accepts (ModelVersion in device-management-api.yaml). */
const MODEL_VERSION = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;

/** An empty field is left to Validators.required. */
const wholeNumber: ValidatorFn = (control: AbstractControl): ValidationErrors | null =>
  control.value === null || Number.isInteger(control.value) ? null : { wholeNumber: true };

/** A number between min and max: the limits of the contract. */
function between(min: number, max: number): ValidatorFn[] {
  return [Validators.required, Validators.min(min), Validators.max(max)];
}

function wholeBetween(min: number, max: number): ValidatorFn[] {
  return [...between(min, max), wholeNumber];
}

/**
 * The configuration of the device in a form. It holds every value but shows only the fields of
 * one section. Save sends the whole form with the version that was read, because PUT replaces the
 * whole configuration.
 */
@Component({
  selector: 'app-device-config-form',
  imports: [ReactiveFormsModule],
  templateUrl: './device-config-form.html',
  styleUrl: './device-config-form.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DeviceConfigForm implements OnInit {
  readonly config = input.required<DeviceConfigurationResponse>();
  readonly section = input.required<ConfigSection>();
  readonly saving = input(false);
  /** fields[] of the last 400 VALIDATION_FAILED. */
  readonly serverErrors = input<FieldError[]>([]);
  readonly save = output<UpdateDeviceConfigurationRequest>();

  private readonly fb = inject(NonNullableFormBuilder);

  protected readonly form = this.fb.group({
    plateCooldownSeconds: [0, wholeBetween(0, 3600)],
    models: this.fb.group({
      detector: ['', [Validators.required, Validators.pattern(MODEL_VERSION)]],
      ocr: ['', [Validators.required, Validators.pattern(MODEL_VERSION)]],
    }),
    ml: this.fb.group({
      detectorMinConfidence: [0, between(0, 1)],
      ocrMinConfidence: [0, between(0, 1)],
      readableMinProbability: [0, between(0, 1)],
      minPlateWidthPx: [0, wholeBetween(10, 4056)],
      minEdgeMarginPx: [0, wholeBetween(0, 1000)],
    }),
    intervals: this.fb.group({
      metricsSeconds: [0, wholeBetween(3, 3600)],
      configPollSeconds: [0, wholeBetween(3, 3600)],
      alertsPollSeconds: [0, wholeBetween(3, 3600)],
      locationSampleSeconds: [0, wholeBetween(1, 3600)],
    }),
    gps: this.fb.group({
      maxFixAgeSeconds: [0, wholeBetween(1, 300)],
    }),
    batching: this.fb.group({
      detectionsBatchSize: [0, wholeBetween(1, 100)],
      locationsBatchSize: [0, wholeBetween(1, 500)],
      imageUrlsBatchSize: [0, wholeBetween(1, 100)],
      maxBatchDelaySeconds: [0, wholeBetween(1, 300)],
      imageUploadsLowPriority: false,
    }),
    photos: this.fb.group({
      widthPx: [0, wholeBetween(640, 4056)],
      jpegQuality: [0, wholeBetween(50, 100)],
      maxWaitingFrames: [0, wholeBetween(1, 10)],
      maxStored: [0, wholeBetween(10, 20000)],
    }),
    camera: this.fb.group({
      fps: [0, between(0.1, 11.7)],
      hflip: false,
      vflip: false,
      exposure: this.fb.group({
        mode: ExposureConfigurationModeEnum.Auto,
        exposureUs: [0, wholeBetween(20, 80000)],
        gain: [0, between(1, 22)],
        maxExposureUs: [0, wholeBetween(20, 80000)],
        maxGain: [0, between(1, 22)],
        targetBrightness: [0, between(0.1, 0.8)],
        meteringTop: [0, between(0, 0.95)],
        meteringBottom: [0, between(0.05, 1)],
      }),
      whiteBalance: this.fb.group({
        mode: WhiteBalanceConfigurationModeEnum.Auto,
        redGain: [0, between(0.5, 8)],
        blueGain: [0, between(0.5, 8)],
      }),
    }),
  });

  constructor() {
    // Marks every refused field; typing in it runs the validators again, which drops the mark.
    effect(() => {
      for (const error of this.serverErrors()) {
        const control = this.form.get(error.field);
        control?.setErrors({ ...control.errors, server: serverMessage(error) });
      }
    });
  }

  ngOnInit(): void {
    this.form.patchValue(this.config());
  }

  /** The message under a field, or null when it is fine. */
  protected errorOf(path: string): string | null {
    const control = this.form.get(path);
    const errors = control?.errors;
    if (!control || !errors) {
      return null;
    }
    if (errors['server']) {
      return errors['server'];
    }
    // The browser's own checks wait until the person leaves the field or presses Save.
    if (!control.touched) {
      return null;
    }
    if (errors['required']) {
      return 'Enter a value.';
    }
    if (errors['wholeNumber']) {
      return 'Enter a whole number.';
    }
    if (errors['min']) {
      return `Must be at least ${errors['min'].min}.`;
    }
    if (errors['max']) {
      return `Must be at most ${errors['max'].max}.`;
    }
    if (errors['pattern']) {
      return 'Use letters, digits, ".", "_" or "-", up to 64 characters.';
    }
    return 'Invalid value.';
  }

  protected submit(): void {
    // A value the server refused is sent again: only the server can tell whether it is fine now.
    for (const error of this.serverErrors()) {
      this.form.get(error.field)?.updateValueAndValidity();
    }
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    this.save.emit({ version: this.config().version, ...this.form.getRawValue() });
  }
}
