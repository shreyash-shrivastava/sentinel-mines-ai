"""SENTINEL Raspberry Pi 5 camera and sensor dashboard."""
import os
os.environ.setdefault('GPIOZERO_PIN_FACTORY', 'lgpio')
import threading
import time
import logging
from pathlib import Path

import cv2
from flask import Flask, Response, jsonify, render_template, request

logging.basicConfig(level=logging.INFO)
log = logging.getLogger('sentinel')
app = Flask(__name__)
CAMERA_DEVICE = int(os.getenv('CAMERA_DEVICE', '0'))
MODEL_PATH = os.getenv('MODEL_PATH', 'yolo11n.pt')
ENABLE_AI = os.getenv('ENABLE_AI', '1') == '1'
ENABLE_SENSORS = os.getenv('ENABLE_SENSORS', '1') == '1'
CONFIDENCE = float(os.getenv('CONFIDENCE', '0.4'))

state_lock = threading.Lock()
state = {
    'temperature': None, 'humidity': None, 'distance': None,
    'dht_status': 'Not started', 'distance_status': 'Not started',
    'camera_status': 'Not started', 'ai_status': 'Disabled',
    'persons': 0, 'objects': 0, 'detections': [], 'ai_timestamp': 0,
}
frame_lock = threading.Lock()
latest_frame = None


def sensors_loop():
    dht = sonar = None
    try:
        import board
        import adafruit_dht
        from gpiozero import DistanceSensor
        try:
            dht = adafruit_dht.DHT11(board.D4, use_pulseio=False)
        except Exception as exc:
            log.warning('DHT init: %s', exc)
        try:
            sonar = DistanceSensor(echo=24, trigger=23, max_distance=3, queue_len=5)
        except Exception as exc:
            log.warning('Sonar init: %s', exc)
    except Exception as exc:
        log.warning('Sensor dependencies unavailable: %s', exc)
    while True:
        update = {'temperature': None, 'humidity': None, 'distance': None,
                  'dht_status': 'Unavailable', 'distance_status': 'Unavailable'}
        if dht:
            try:
                update['temperature'] = dht.temperature
                update['humidity'] = dht.humidity
                update['dht_status'] = 'Connected' if None not in (update['temperature'], update['humidity']) else 'No reading'
            except Exception as exc:
                update['dht_status'] = str(exc)[:160]
        if sonar:
            try:
                update['distance'] = round(sonar.distance * 100, 1)
                update['distance_status'] = 'Connected'
            except Exception as exc:
                update['distance_status'] = str(exc)[:160]
        with state_lock:
            state.update(update)
        time.sleep(2)


def camera_loop():
    global latest_frame
    while True:
        cap = cv2.VideoCapture(CAMERA_DEVICE, cv2.CAP_V4L2)
        if not cap.isOpened():
            with state_lock:
                state['camera_status'] = f'Camera /dev/video{CAMERA_DEVICE} unavailable'
            time.sleep(3)
            continue
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_FPS, 15)
        with state_lock:
            state['camera_status'] = 'Connected'
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            with frame_lock:
                latest_frame = frame
        cap.release()
        with frame_lock:
            latest_frame = None
        with state_lock:
            state['camera_status'] = 'Disconnected; reconnecting'
        time.sleep(2)


def ai_loop():
    if not ENABLE_AI:
        return
    try:
        from ultralytics import YOLO
        model = YOLO(MODEL_PATH)
    except Exception as exc:
        with state_lock:
            state['ai_status'] = f'Load failed: {exc}'[:180]
        log.exception('AI initialization failed')
        return
    while True:
        with frame_lock:
            frame = latest_frame.copy() if latest_frame is not None else None
        if frame is None:
            with state_lock:
                state.update(ai_status='Waiting for camera', persons=0, objects=0, detections=[], ai_timestamp=0)
            time.sleep(.4)
            continue
        try:
            result = model.predict(frame, imgsz=320, conf=CONFIDENCE, verbose=False)[0]
            detections = []
            for b in result.boxes:
                cls = int(b.cls[0])
                detections.append({
                    'label': str(model.names[cls]), 'confidence': round(float(b.conf[0]), 2),
                    'box': [int(n) for n in b.xyxy[0].tolist()],
                })
            with state_lock:
                state.update(ai_status='Running', persons=sum(d['label'] == 'person' for d in detections),
                             objects=len(detections), detections=detections, ai_timestamp=time.time())
        except Exception as exc:
            with state_lock:
                state.update(ai_status=f'Inference failed: {exc}'[:180], persons=0, objects=0, detections=[], ai_timestamp=0)
            time.sleep(1)


def process(frame, filter_name, strength, detection):
    strength = max(0, min(100, strength)) / 100.0
    if filter_name != 'normal':
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if filter_name == 'jet':
            filtered = cv2.applyColorMap(gray, cv2.COLORMAP_JET)
        elif filter_name == 'inferno':
            filtered = cv2.applyColorMap(gray, cv2.COLORMAP_INFERNO)
        elif filter_name == 'gray':
            filtered = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        elif filter_name == 'edges':
            filtered = cv2.cvtColor(cv2.Canny(gray, 60, 140), cv2.COLOR_GRAY2BGR)
        else:
            filtered = frame
        frame = cv2.addWeighted(frame, 1 - strength, filtered, strength, 0)
    if detection != 'off':
        with state_lock:
            detections = list(state['detections']) if time.time() - state['ai_timestamp'] < 2 else []
        for d in detections:
            if detection == 'person' and d['label'] != 'person':
                continue
            x1, y1, x2, y2 = d['box']
            color = (0, 220, 80) if d['label'] == 'person' else (255, 180, 0)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, f"{d['label']} {d['confidence']:.0%}",
                        (x1, max(20, y1-7)), cv2.FONT_HERSHEY_SIMPLEX, .5, color, 2)
    return frame


def video_stream(filter_name, strength, detection):
    while True:
        with frame_lock:
            frame = latest_frame.copy() if latest_frame is not None else None
        if frame is None:
            time.sleep(.2)
            continue
        frame = process(frame, filter_name, strength, detection)
        ok, jpg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if ok:
            yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpg.tobytes() + b'\r\n'
        time.sleep(1 / 15)


@app.get('/')
def index():
    return render_template('index.html')


@app.get('/api/status')
def status():
    with state_lock:
        d = state.copy()
        d['detections'] = list(state['detections'])
    if time.time() - d['ai_timestamp'] > 2:
        d.update(persons=0, objects=0, detections=[])
    return jsonify(d)


@app.get('/video_feed')
def video_feed():
    name = request.args.get('filter', 'normal')
    detection = request.args.get('detect', 'all')
    try:
        strength = int(request.args.get('strength', '100'))
    except ValueError:
        strength = 100
    if name not in ('normal', 'jet', 'inferno', 'gray', 'edges'):
        name = 'normal'
    if detection not in ('all', 'person', 'off'):
        detection = 'all'
    return Response(video_stream(name, strength, detection),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


def main():
    if ENABLE_SENSORS:
        threading.Thread(target=sensors_loop, daemon=True).start()
    threading.Thread(target=camera_loop, daemon=True).start()
    if ENABLE_AI:
        threading.Thread(target=ai_loop, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', '5000')), threaded=True, debug=False)


if __name__ == '__main__':
    main()
