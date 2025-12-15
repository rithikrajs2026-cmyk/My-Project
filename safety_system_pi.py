import cv2
import numpy as np
import time
import requests
import socket
import json
import threading
import RPi.GPIO as GPIO
import blynklib

# IMPORT TENSORFLOW LITE RUNTIME
try:
    import tflite_runtime.interpreter as tflite
except ImportError:
    try:
        import tensorflow.lite.python.interpreter as tflite
    except ImportError:
        print("Error: Install tflite-runtime using: pip3 install tflite-runtime")
        exit()

# ================= CONFIGURATION =================
# BLYNK CONFIGURATION
BLYNK_TEMPLATE_ID = "TMPL3Mr4q6d9J"
BLYNK_TEMPLATE_NAME = "Safety System"
BLYNK_AUTH = "pODLNoH_026h4mlC-AaAN8XA2ozvsOsf"

# IMGBB CONFIGURATION
IMGBB_API_KEY = 'd72547ffc90ee5788f77e6193e360c11'

HOST = '0.0.0.0' # Listen on all network interfaces
PORT = 65432     # Port to listen for ESP32
RELAY_PIN = 17   # GPIO Pin for Relay

# THRESHOLDS
TDS_THRESHOLD = 1000.0   # Alert if TDS > 1000 ppm
TURBIDITY_THRESHOLD = 10.0
PH_LOW = 6.0
PH_HIGH = 8.5

# CUSTOM MODEL FILES
MODEL_PATH = "model.tflite"
LABELS_PATH = "labels.txt"
CONFIDENCE_THRESHOLD = 0.70 

# ================= GLOBAL VARIABLES =================
system_status = "SAFE"
valve_is_open = True
last_alert_time = 0

# ================= HARDWARE SETUP =================
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
GPIO.setup(RELAY_PIN, GPIO.OUT)
GPIO.output(RELAY_PIN, GPIO.HIGH) 

# Initialize Blynk
print("[INIT] Connecting to Blynk...")
try:
    blynk = blynklib.Blynk(BLYNK_AUTH)
except:
    print("[ERROR] Blynk Connection Failed. Check Internet.")

# LOAD CUSTOM LABELS AND MODEL
print("[INIT] Loading AI Resources...")
try:
    with open(LABELS_PATH, 'r') as f:
        labels = [line.strip() for line in f.readlines()]
    interpreter = tflite.Interpreter(model_path=MODEL_PATH)
    interpreter.allocate_tensors()
except Exception as e:
    print(f"[ERROR] Resource load failed: {e}")
    exit()

input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()
height = input_details[0]['shape'][1]
width = input_details[0]['shape'][2]

# ================= HELPER FUNCTIONS =================

def emergency_shutdown(reason, evidence_image=None):
    """Closes valve, takes action, and alerts user"""
    global system_status, valve_is_open, last_alert_time
    
    # ACTION: Close Valve
    GPIO.output(RELAY_PIN, GPIO.LOW) 
    valve_is_open = False
    system_status = "DANGER"
    
    if time.time() - last_alert_time < 30: return

    print(f"\n[!!! DANGER !!!] Trigger: {reason}")
    
    # UPLOAD IMAGE
    image_url = "[https://i.ibb.co/Placeholder/error.png](https://i.ibb.co/Placeholder/error.png)"
    if evidence_image is not None:
        filename = f"alert_{int(time.time())}.jpg"
        cv2.imwrite(filename, evidence_image)
        import base64
        try:
            with open(filename, "rb") as img_file:
                b64_image = base64.b64encode(img_file.read())     
            payload = {'key': IMGBB_API_KEY, 'image': b64_image}
            res = requests.post("[https://api.imgbb.com/1/upload](https://api.imgbb.com/1/upload)", data=payload)
            data = res.json()
            if data['success']:
                image_url = data['data']['url']
        except Exception: pass

    # SEND TO BLYNK
    try:
        blynk.log_event("critical_alert", f"⚠️ DANGER: {reason}")
        blynk.virtual_write(0, f"⚠️ {reason}") 
        blynk.virtual_write(1, image_url)              
        blynk.virtual_write(4, "CLOSED 🔴")            
    except: pass

    last_alert_time = time.time()

# ================= THREAD 1: CUSTOM AI LOOP =================
def camera_ai_loop():
    print("[THREAD] AI Camera Started")
    cap = cv2.VideoCapture(0)
    
    while True:
        ret, frame = cap.read()
        if not ret: 
            time.sleep(0.5); continue

        image_resized = cv2.resize(frame, (width, height))
        input_data = np.expand_dims(image_resized, axis=0)
        
        if input_details[0]['dtype'] == np.float32:
            input_data = (np.float32(input_data) - 127.5) / 127.5

        interpreter.set_tensor(input_details[0]['index'], input_data)
        interpreter.invoke()

        output_data = interpreter.get_tensor(output_details[0]['index'])
        results = np.squeeze(output_data)
        top_index = np.argmax(results)
        confidence = results[top_index]
        if output_details[0]['dtype'] == np.uint8: confidence = confidence / 255.0

        detected_label = labels[top_index]

        if confidence > CONFIDENCE_THRESHOLD:
            if "Danger" in detected_label or "Fire" in detected_label:
                emergency_shutdown(f"Visual: {detected_label}", frame)
    cap.release()

# ================= THREAD 2: SENSOR LISTENER =================
def sensor_listener_loop():
    print("[THREAD] Sensor Listener Started")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((HOST, PORT))
            s.listen()
        except Exception: return

        while True:
            try:
                conn, addr = s.accept()
                with conn:
                    data = conn.recv(1024)
                    if not data: continue
                    try:
                        readings = json.loads(data.decode('utf-8'))
                        ph = float(readings.get('ph', 0))
                        turb = float(readings.get('turbidity', 0))
                        tds = float(readings.get('tds', 0))
                        
                        is_bad = (ph < PH_LOW or ph > PH_HIGH or turb > TURBIDITY_THRESHOLD or tds > TDS_THRESHOLD)

                        if is_bad:
                            reason = f"Chem: pH{ph}/Tb{turb}/TDS{tds}"
                            emergency_shutdown(reason)
                        
                        if system_status == "SAFE":
                            blynk.virtual_write(2, ph)
                            blynk.virtual_write(3, turb)
                            blynk.virtual_write(5, tds)
                    except: pass
            except: pass

if __name__ == "__main__":
    t1 = threading.Thread(target=camera_ai_loop)
    t1.daemon = True
    t1.start()
    t2 = threading.Thread(target=sensor_listener_loop)
    t2.daemon = True
    t2.start()
    print("[SYSTEM] System Online.")
    try:
        while True: blynk.run(); time.sleep(0.1)
    except KeyboardInterrupt: GPIO.cleanup()