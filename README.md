# CineMate – manual controls for CinePi v2
CineMate Python scripts is a way for users to implement and customize manual controls for their CinePi v2 build. 

Project aims at offering an easy way to build a custom camera. For basic operation and experimentation, only Raspberry Pi, camera board and monitor. For practical use, buttons and switches can easily be added, allowing for a custom build.

## Functions
- Enables recording and various camera controls via the **RPi GPIO**, **USB Keyboard/Numpad**, **serial input** via USB (works with any microcontroller writing to serial) and (a rudimentary) **CineMate CLI** via SSH.
- Simple GUI on the HDMI display.
- Recording of audio scratch track using a USB microphone.
- System button for safe shutdown, start-up and unmounting of SSD drive.
- Attach a Grove Base HAT and control of iso, shutter angle and fps via potentiometers.

For users experimenting with their own build/GPIO configuration, scripts output extensive logging info.

## Hardware setup
In order to get cinepi-raw and CineMate scripts running, you need:

- Raspberry Pi 4B (4 or 8 GB versions have been tested)
- Raspberry Pi IMX477 HQ camera board (rolling/global shutter variants both work)
- HDMI capable monitor/computer screen

For recording raw frames, a fast SSD is needed. Samsung T5/T7 will work. SSD needs to be formatted as NTFS and named "RAW".

For hardware control of camera settings and recording, see below.

## Installation
### Preinstalled image 
Preinstalled image file with Raspbian, cinepi-raw and CineMate scripts can be found in the release section of this repository. Burn this image onto an SD card and start up the Pi. Make sure you have an HDMI monitor hooked up on startup, in order for the simple gui module to start up properly.

The scripts can be also manually installed onto a Rasberry Pi 4B already running CinePi v2. 

### Manual install
#### Dependencies
`sudo apt update`

`sudo apt upgrade`

`sudo apt full-upgrade` (updates Raspbian, enabling the Raspberry Pi Global Shutter camera)

`sudo apt install python3-pip`

`sudo apt-get install -y i2c-tools portaudio19-dev`

`sudo pip3 install psutil Pillow redis keyboard pyudev sounddevice smbus2 gpiozero RPI.GPIO evdev termcolor pyserial inotify_simple`

#### Grove Base HAT
`sudo apt-get install build-essential python3-dev python3-pip python3-smbus python3-serial git`

`sudo pip3 install -U setuptools wheel`

`sudo pip3 install -U grove.py`

`git clone https://github.com/Seeed-Studio/grove.py.git``

`cd grove.py`

`sudo python3 setup.py install`

`sudo raspi-config`

3 Interface Options > I5 I2C Enable > Yes

`sudo reboot`

#### CineMate scripts
`git clone https://github.com/Tiramisioux/cinemate.git`

`cd cinemate``

`make install`

`main.py` will now run automatically at startup.

### Starting and stopping CineMate
`cd cinemate`

`make start` / `make stop`

`main.py` is located in the cinemate/src folder and can be manually started from there:

`cd cinemate/src`

`sudo python3 main.py`

Note that `main.py` must be run as root.

### Disable/enable automatic start of CineMate scripts:
in `/home/pi/cinemate/`:

`make uninstall` / `make install`

## Controlling the camera 
Camera settings can be set by using any one of the following methods:

1) Connecting to the Pi via SSH and running the CineMate scripts manually (see above), allowing for a rudimentary CLI.
2) Connecting a USB Keyboard or Numpad to the Pi.
3) Connecting push buttons to the GPIOs of the Raspberry Pi.
4) Serial control from a microcontroller (such as the Raspberry Pico) connected via USB.
5) Using a Seeed Grove Base HAT, allowing for control using Grove buttons and potentiometers.

|CLI (via SSH) and serial|GPIO|Keyboard/Num pad|Grove Base HAT|Function|
|---|---|---|---|---|
|`rec`|4, 6, 22|`9`|D6, D22|start/stop recording|
|      |5||D5|LED or rec light indicator (be sure to use a 320k resistor on this pin!|
|`res 1080` / `res 1520`|13, 24|8|D24|change resolution (cropped and full frame)|
|`iso inc`|25|`1`||ISO decrease|
|`iso dec`|23|`2`||ISO increase|
|`shutter_a inc`||`3`||shutter angle decrease|
|`shutter_a dec`||`4`||shutter angle increase|
|`fps inc`||`5`||fps decrease|
|`fps dec`||`6`||fps increase|
||18||D18|50% frame rate|
||19||D19|200% frame rate (up to 50 fps)|
||16||D16|lock shutter angle and frame rate controls|
|`iso` + `value`|||A0|change iso|
|`shutter_a` + `value`|||A2|change shutter angle|
|`fps` + `value`|||A4|change fps|
|`unmount`|26|`0`|D26|unmount SSD (double click) / safe shutdown (triple click)|
|`get`||||prints current camera settings to the CLI|
|`time`||||prints system time and RTC time to the cli|
|`set time`||||sets RTC time to system time|

GPIO settings and arrays for legal values can be customized in `main.py`.

TIP! Connect GPIO 26 to GPIO 03 using a jumper wire, and the safe shutdown button attached to GPIO 26 will also wake up the Pi, after being shutdown.

### Mapping iso, shutter_a and fps to default arrays

When changing iso, shutter angle or fps using the `inc` or `dec` commands, default arrays are used. This can be helpful to limit the amount of possible values, making hardware controls easier to design. 

|Camera setting|Default legal values|
|---|---|
|ISO |100, 200, 400, 640, 800, 1200, 1600, 2500, 3200|
|Shutter angle |45, 90, 135, 172.8, 180, 225, 270, 315, 346.6, 360|
|FPS |1, 2, 4, 8, 16, 18, 24, 25, 33, 48, 50|

Above default arrays can be customized in `main.py`. 

### Precise control of iso, shutter_a and fps 

When setting iso, shutter angle or fps using Cinemate CLI or serial control, any value can be set. 

For CineMate CLI/serial, type the `control name` + `blank space` + `value`. Iso accepts integers. Shutter angle accepts floating point numbers with one decimal. 

`iso 450` 

`shutter_a 23.4`

`fps 31` 

## Ideas for build
Tinkercad model for the below build can be found here:

https://www.tinkercad.com/things/eNhTTYdgOM0


Step by step instruction + parts list coming soon.

## Known issues

- HDMI monitor has to be connected on startup for scripts to work.
- Sometimes script does not recognize SSD drive on startup. Then try disconnecting and connecting the drive again.
- Be sure to do a safe shutdown of the Pi before removing the SSD, otherwise the last two clip folders on the drive might become corrupted.

## Notes on audio sync

Actual frame rate of the IMX477 sensor fluctuates about 0.01% around the mean value. This has no visual impact but will impact syncing of external audio. If recording synced audio, make sure to use a clapper board in the beginning and the end of the take. This will make it easier to sync the sound, but sync might still drift back and forth.

Solution to this might be to use an external trigger for the camera board, like suggested here:

Currently investigating the possibility to use the hardware PWM signal on the Pi, fed to the camera board via a voltage divider, for the frame rate to be dead on the selected value.

## Notes on RTC

Cinepi-raw names the clips according to system time. For clips to use the current time of day, an RTC (realtime clock unit) can be installed.

To get the right system time on the Pi, simply connect to a computer connected to the internet via SSH and the Pi will update its system time.

To check system time in the CineMate CLI, type `time`

To write system time to a connected RTC, in the Cinemate CLI, type `set time`. 

Now, if not connected to the internet, on startup the Pi will get its system time from the RTC.


## Notes on rec light logic

Occationaly, the red color in the simple gui, and the LED conencted to the rec light output might blink. This is expected behaviour and does not mean frames are dropped.

The reason is that the rec light logic is based on whether frames are writted to the SSD. Occationaly, cinepi-raw buffers frames before writing them to the SSD, leading to a brief pause in the writing of files to the SSD, causing the light to blink.