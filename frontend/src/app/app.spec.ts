import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { App } from './app';
import { NotificationService } from './core/notification.service';

describe('App', () => {
  it('shows an error notice as an alert and closes it', async () => {
    TestBed.configureTestingModule({ imports: [App], providers: [provideRouter([])] });
    const fixture = TestBed.createComponent(App);
    TestBed.inject(NotificationService).error('Cannot reach the server.');
    await fixture.whenStable();
    fixture.detectChanges();

    const notice: HTMLElement = fixture.nativeElement.querySelector('[role="alert"]');
    expect(notice.textContent).toContain('Cannot reach the server.');

    (notice.querySelector('button') as HTMLButtonElement).click();
    await fixture.whenStable();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[role="alert"]')).toBeNull();
  });
});
