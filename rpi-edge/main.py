from gpiozero import LED, Buzzer, Button
from signal import pause
from RPLCD.i2c import CharLCD

lcd = CharLCD(
    i2c_expander='PCF8574',
    address=0x27,
    port=1,
    cols=20,
    rows=4,
    dotsize=8,
    charmap='A02',
    auto_linebreaks=True,
)

led = LED(17)
buzzer = Buzzer(27)
button = Button(22)

def pressed():
    led.blink(0.03, 0.03, 10)
    buzzer.blink(0.03, 0.03, 10)
    lcd.write_string("Test! ")

lcd.clear()
button.when_pressed = pressed



pause()
