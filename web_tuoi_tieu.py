# web_esp.py
import streamlit as st
from datetime import datetime, timedelta, date, time
import random
from PIL import Image
import requests
import json
import os
from streamlit_autorefresh import st_autorefresh
import pytz
import pandas as pd
import paho.mqtt.client as mqtt
import threading

# -----------------------
# Config & helpers
# -----------------------
st.set_page_config(page_title="Smart Irrigation WebApp", layout="wide")
st_autorefresh(interval=60 * 1000, key="init_refresh")

# --- I18N ---
lang = st.sidebar.selectbox("🌐 Language / Ngôn ngữ", ["Tiếng Việt", "English"])
vi = lang == "Tiếng Việt"
def _(vi_text, en_text):
    return vi_text if vi else en_text

# Files
DATA_FILE = "crop_data.json"
HISTORY_FILE = "history_irrigation.json"
FLOW_FILE = "flow_data.json"  # lưu dữ liệu lưu lượng (esp32) theo thời gian
CONFIG_FILE = "config.json"   # lưu cấu hình chung: khung giờ tưới + chế độ

def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return default
    else:
        return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# Hàm thêm record cảm biến vào history
def add_history_record(sensor_hum, sensor_temp):
    now_iso = datetime.now(vn_tz).isoformat()
    new_record = {
        "timestamp": now_iso,
        "sensor_hum": sensor_hum,
        "sensor_temp": sensor_temp
    }
    history = load_json(HISTORY_FILE, [])
    history.append(new_record)
    save_json(HISTORY_FILE, history)

# Hàm thêm record lưu lượng vào flow_data
def add_flow_record(flow_val):
    now_iso = datetime.now(vn_tz).isoformat()
    new_record = {
        "time": now_iso,
        "flow": flow_val
    }
    flow = load_json(FLOW_FILE, [])
    flow.append(new_record)
    save_json(FLOW_FILE, flow)

# Load persistent data
crop_data = load_json(DATA_FILE, {})
history_data = load_json(HISTORY_FILE, [])
flow_data = load_json(FLOW_FILE, [])
config = load_json(CONFIG_FILE, {"watering_schedule": "06:00-08:00", "mode": "auto"})

# timezone
vn_tz = pytz.timezone("Asia/Ho_Chi_Minh")
now = datetime.now(vn_tz)

# -----------------------
# MQTT - Hàm gửi lệnh bật/tắt bơm qua MQTT
# -----------------------
MQTT_BROKER = "test.mosquitto.org"  # hoặc broker MQTT của bạn
MQTT_PORT = 1883
MQTT_TOPIC_PUMP = "smart_irrigation/pump_control"

def mqtt_send_pump_command(state: bool):
    client = mqtt.Client()
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        payload = "ON" if state else "OFF"
        client.publish(MQTT_TOPIC_PUMP, payload)
        client.disconnect()
        return True
    except Exception as e:
        st.error(f"Lỗi gửi lệnh bơm qua MQTT: {e}")
        return False

# -----------------------
# UI - Header & Logo (unchanged) ...
# -----------------------
# ... your existing UI and logic code here unchanged ...

# -----------------------
# Mode and Watering Schedule (shared config.json)
# -----------------------
st.header(_("⚙️ Cấu hình chung hệ thống", "⚙️ System General Configuration"))

if user_type == _("Người điều khiển", "Control Administrator"):
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(_("### ⏲️ Khung giờ tưới nước", "### ⏲️ Watering time window"))
        start_time = st.time_input(
            _("Giờ bắt đầu", "Start time"),
            value=datetime.strptime(config["watering_schedule"].split("-")[0], "%H:%M").time(),
        )
        end_time = st.time_input(
            _("Giờ kết thúc", "End time"),
            value=datetime.strptime(config["watering_schedule"].split("-")[1], "%H:%M").time(),
        )
    with col2:
        st.markdown(_("### 🔄 Chọn chế độ", "### 🔄 Select operation mode"))
        main_mode = st.radio(
            _("Chọn chế độ điều khiển", "Select control mode"),
            [_("Tự động", "Automatic"), _("Thủ công", "Manual")],
            index=0 if config.get("mode", "auto") == "auto" else 1,
        )

        manual_control_type = None
        if main_mode == _("Thủ công", "Manual"):
            manual_control_type = st.radio(
                _("Chọn phương thức thủ công", "Select manual control type"),
                [_("Thủ công trên app", "Manual on app"), _("Thủ công ở tủ điện", "Manual on cabinet")],
            )

    if st.button(_("💾 Lưu cấu hình", "💾 Save configuration")):
        config["watering_schedule"] = f"{start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')}"
        if main_mode == _("Tự động", "Automatic"):
            config["mode"] = "auto"
            config.pop("manual_control_type", None)
        else:
            config["mode"] = "manual"
            config["manual_control_type"] = manual_control_type
        save_json(CONFIG_FILE, config)
        st.success(_("Đã lưu cấu hình.", "Configuration saved."))

else:
    st.markdown(
        _("⏲️ Khung giờ tưới nước hiện tại:", "⏲️ Current watering time window:") + f" **{config['watering_schedule']}**"
    )
    mode_display = _("Tự động", "Automatic") if config.get("mode", "auto") == "auto" else _("Thủ công", "Manual")
    st.markdown(_("🔄 Chế độ hoạt động hiện tại:", "🔄 Current operation mode:") + f" **{mode_display}**")
    if config.get("mode") == "manual":
        manual_type_display = config.get("manual_control_type", "")
        if manual_type_display == _("Thủ công trên app", "Manual on app") or manual_type_display == "Manual on app":
            st.markdown(_("⚙️ Phương thức thủ công: Thủ công trên app", "⚙️ Manual method: Manual on app"))
        elif manual_type_display == _("Thủ công ở tủ điện", "Manual on cabinet") or manual_type_display == "Manual on cabinet":
            st.markdown(_("⚙️ Phương thức thủ công: Thủ công ở tủ điện", "⚙️ Manual method: Manual on cabinet"))

# -----------------------
# Phần xử lý tưới trong chế độ thủ công trên app (chèn phần 4)
# -----------------------
should_water = False
if config.get("mode") == "auto":
    # Logic tưới tự động của bạn (giữ nguyên)
    # Ví dụ:
    # should_water = simulated_soil_moisture < 65 and is_in_watering_time
    pass
elif config.get("mode") == "manual":
    manual_control_type = config.get("manual_control_type", None)
    if manual_control_type == _("Thủ công trên app", "Manual on app") or manual_control_type == "Manual on app":
        st.warning(_("⚠️ Đang ở chế độ thủ công trên app. Bạn có thể bật hoặc tắt bơm thủ công.", "⚠️ Manual control on app. You can turn pump ON or OFF manually."))

        col_on, col_off = st.columns(2)
        with col_on:
            if st.button(_("Bật bơm thủ công", "Turn ON pump manually")):
                if mqtt_send_pump_command(True):
                    st.success(_("Đã gửi lệnh bật bơm qua MQTT", "Sent command to turn ON pump via MQTT"))
        with col_off:
            if st.button(_("Tắt bơm thủ công", "Turn OFF pump manually")):
                if mqtt_send_pump_command(False):
                    st.success(_("Đã gửi lệnh tắt bơm qua MQTT", "Sent command to turn OFF pump via MQTT"))

        should_water = False  # Khi thủ công trên app, tạm không tưới tự động
    else:
        # Thủ công ở tủ điện, không điều khiển được trên app
        st.info(
            _(
                "Chế độ thủ công ở tủ điện, không thể điều khiển bơm trên app. Vui lòng thao tác trên tủ điện.",
                "Manual mode on cabinet, cannot control pump on app. Please operate on cabinet.",
            )
        )
        should_water = False

if should_water:
    st.warning(_("⚠️ Cần tưới nước cho cây trồng.", "⚠️ Irrigation is needed for crops."))
else:
    st.info(_("💧 Không cần tưới nước lúc này.", "💧 No irrigation needed at this moment."))

# -----------------------
# Phần còn lại code của bạn giữ nguyên
# -----------------------
# ... tiếp tục với phần lịch sử, biểu đồ, MQTT subscribe... (giữ nguyên)

# ... MQTT subscribe và xử lý (giữ nguyên) ...
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("MQTT connected successfully")
        client.subscribe(TOPIC_DATA)
    else:
        print(f"MQTT failed to connect, return code {rc}")

def on_message(client, userdata, msg):
    try:
        payload_str = msg.payload.decode()
        print(f"MQTT message received on {msg.topic}: {payload_str}")
        data = json.loads(payload_str)

        soil_moisture = data.get("soil_moisture", 100)

        # Đơn giản: nếu độ ẩm đất < 65, gửi lệnh bật bơm, ngược lại tắt bơm
        if soil_moisture < 65:
            print("Soil moisture low, sending pump_on command")
            client.publish(TOPIC_COMMAND, "pump_on")
        else:
            print("Soil moisture sufficient, sending pump_off command")
            client.publish(TOPIC_COMMAND, "pump_off")
    except Exception as e:
        print(f"Error processing MQTT message: {e}")

def mqtt_thread():
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_forever()
    except Exception as e:
        print(f"MQTT connection error: {e}")

# Start MQTT client in background thread
threading.Thread(target=mqtt_thread, daemon=True).start()

# -----------------------
# Footer (unchanged)
# -----------------------
st.markdown("---")
st.caption("📡 API thời tiết: Open-Meteo | Dữ liệu cảm biến: ESP32-WROOM (giả lập nếu chưa có)")
st.caption("Người thực hiện: Ngô Nguyễn Định Tường-Mai Phúc Khang")
