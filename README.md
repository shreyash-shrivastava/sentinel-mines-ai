# SENTINEL AI — Raspberry Pi 5 Dashboard

Local Flask dashboard for a Raspberry Pi 5 with a DJI Action 2 UVC webcam, DHT11 temperature/humidity sensor, HC-SR04 range finder, and YOLO person/object detection.

**Features:** MJPEG video, person/object bounding boxes, detection counts, JET/Inferno false-color filters, grayscale/edges, sensor readings. No ESP32 or Arduino required.

> **Safety:** This is an educational rover prototype, not a certified mine-safety device. DJI Action 2 is not a thermal camera: false-color effects depict brightness, *not temperature*. Object detection can miss people and hazards.

## Wiring (physical header pins, Raspberry Pi 5)

| Device | Module pin | Pi physical pin / GPIO |
|---|---|---|
| DHT11 3-pin module | VCC | 1 / 3.3V |
| DHT11 | DATA | 7 / GPIO4 |
| DHT11 | GND | 6 / GND |
| HC-SR04 | VCC | 2 / 5V |
| HC-SR04 | TRIG | 16 / GPIO23 |
| HC-SR04 | ECHO | 18 / GPIO24 **through divider** |
| HC-SR04 | GND | 9 / GND |

**Never connect the HC-SR04 5V ECHO directly to a Pi GPIO.** Use 1kΩ between ECHO and GPIO24, 2kΩ between GPIO24 and GND, or a suitable logic-level shifter. A bare 4-pin DHT11 normally needs a 4.7–10kΩ pull-up between DATA and 3.3V; many 3-pin breakout modules contain it already. Check the module's silkscreen pin order. Power down before rewiring.

MQ-135 is deliberately excluded because it is not currently being used.

## Install on Raspberry Pi OS (64-bit)

```bash
sudo apt update
sudo apt install -y python3-venv python3-opencv python3-lgpio python3-gpiozero v4l-utils
cd sentinel-ai
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

For compatibility with Raspberry Pi OS and OpenCV, the venv uses OS-installed `python3-opencv`. Ultralytics may install other dependencies and download its model on first launch; internet is needed for that initial download. If installation on your Pi fails, check its OS/Python version and the Ultralytics installation guide.

## Camera setup

Connect DJI Action 2 through a USB-capable module, select webcam mode, and run:

```bash
v4l2-ctl --list-devices
ls /dev/video*
```

Find the working video node (may not be `/dev/video0`). Change `CAMERA_DEVICE` in `.env` or export it in your shell. Test capture with:

```bash
CAMERA_DEVICE=0 python -c 'import cv2; c=cv2.VideoCapture(0,cv2.CAP_V4L2); print(c.isOpened(), c.read()[0]); c.release()'
```

Replace `0` with the correct device index. Close other camera apps before launching SENTINEL.

## Run

```bash
source .venv/bin/activate
export CAMERA_DEVICE=0
python app.py
```

Open `http://<PI_IP>:5000` from a browser on the same trusted Wi-Fi. Find your IP with `hostname -I`. **Do not expose this development server directly to the internet**; it has no authentication.

Environment variables (use `export` or source an environment config; `.env` is a sample, not loaded automatically): `CAMERA_DEVICE`, `MODEL_PATH`, `ENABLE_AI`, `ENABLE_SENSORS`, `CONFIDENCE`, `PORT`.

To test the camera/dashboard without sensor hardware, run `ENABLE_SENSORS=0 python app.py`. To troubleshoot AI installs, run `ENABLE_AI=0 python app.py`. AI defaults to `yolo11n.pt`, a small general-purpose pretrained model; the YOLO model may download on its first use. For more speed, investigate exported NCNN inference after initial success.

## DHT11 troubleshooting

The DHT11 has previously shown `Sensor not found`. This code shows status/errors on the dashboard, but **does not repair a wiring problem**. Confirm DATA goes to physical pin 7 (BCM GPIO4), ensure the 3.3V and ground are correct, check pull-up requirements, and close other scripts using the GPIO line. Occasional DHT read failures can happen; this code samples every two seconds.

## Limitations

- Detection is a general object detector, not trained/validated for mine-specific hazards.
- Boxes may lag behind the video because AI runs on a separate inference loop; overlays are not frame-synchronized.
- Distance can report maximum range when an echo is absent; don't use this alone for collision avoidance.
- Each dashboard viewer encodes its own MJPEG stream; keep client count small.
- No gas concentration or safety alarm is included.

## Publish to GitHub

Create an empty repository named `sentinel-ai` in GitHub, then in this directory run:

```bash
git init
git add .
git commit -m "Initial SENTINEL AI dashboard"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/sentinel-ai.git
git push -u origin main
```

Do not commit API keys, Wi-Fi credentials, or private videos.
