# web_esp.py
import streamlit as st
from datetime import datetime, timedelta, date
import json
import os
import pytz
import pandas as pd
import requests
import threading
import paho.mqtt.client as mqtt
import matplotlib.pyplot as plt

# -----------------------
# Config & helpers
# -----------------------
st.set_page_config(page_title="Smart Irrigation WebApp", layout="wide")

# --- I18N ---
lang = st.sidebar.selectbox("🌐 Language / Ngôn ngữ", ["Tiếng Việt", "English"])
vi = lang == "Tiếng Việt"
def _(vi_text, en_text):
    return vi_text if vi else en_text

# Files
DATA_FILE = "crop_data.json"
HISTORY_FILE = "history_irrigation.json"
FLOW_FILE = "flow_data.json"
CONFIG_FILE = "config.json"

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

# timezone
vn_tz = pytz.timezone("Asia/Ho_Chi_Minh")
now = datetime.now(vn_tz)

# MQTT Config
MQTT_BROKER = "test.mosquitto.org"
MQTT_PORT = 1883
TOPIC_SENSOR = "smart_irrigation/sensor_data"
TOPIC_COMMAND = "smart_irrigation/command"

# Global sensor data store (latest)
sensor_data = {
    "soil_moisture": None,
    "temperature": None,
    "water_flow": None,
    "last_update": None,
    "connected": False,
}

# MQTT callbacks
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        sensor_data["connected"] = True
        client.subscribe(TOPIC_SENSOR)
    else:
        sensor_data["connected"] = False

def on_disconnect(client, userdata, rc):
    sensor_data["connected"] = False

def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode()
        data = json.loads(payload)
        # Expect JSON like {"soil_moisture": int, "temperature": int, "water_flow": int}
        sensor_data["soil_moisture"] = data.get("soil_moisture", None)
        sensor_data["temperature"] = data.get("temperature", None)
        sensor_data["water_flow"] = data.get("water_flow", None)
        sensor_data["last_update"] = datetime.now(vn_tz)
    except Exception as e:
        print("MQTT message error:", e)

def mqtt_loop():
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_forever()
    except Exception as e:
        print("MQTT connection failed:", e)
        sensor_data["connected"] = False

# Start MQTT thread
mqtt_thread = threading.Thread(target=mqtt_loop, daemon=True)
mqtt_thread.start()

# -----------------------
# Load persistent data
crop_data = load_json(DATA_FILE, {})
history_data = load_json(HISTORY_FILE, [])
flow_data = load_json(FLOW_FILE, [])
config = load_json(CONFIG_FILE, {"watering_schedule": "06:00-08:00", "mode": "auto"})

# -----------------------
# UI HEADER
st.markdown(f"<h2 style='text-align:center'>🌾 {_('Hệ thống tưới tiêu nông nghiệp thông minh', 'Smart Agricultural Irrigation System')} 🌾</h2>", unsafe_allow_html=True)
st.markdown(f"<p style='text-align:center'>{_('Thời gian hiện tại', 'Current time')}: {now.strftime('%d/%m/%Y %H:%M:%S')}</p>", unsafe_allow_html=True)

# -----------------------
# Sidebar role and auth
st.sidebar.title(_("🔐 Chọn vai trò người dùng", "🔐 Select User Role"))
user_type = st.sidebar.radio(_("Bạn là:", "You are:"), [_("Người điều khiển", "Control Administrator"), _("Người giám sát", "Monitoring Officer")])

if user_type == _("Người điều khiển", "Control Administrator"):
    password = st.sidebar.text_input(_("🔑 Nhập mật khẩu:", "🔑 Enter password:"), type="password")
    if password != "admin123":
        st.sidebar.error(_("❌ Mật khẩu sai. Truy cập bị từ chối.", "❌ Incorrect password. Access denied."))
        st.stop()
    else:
        st.sidebar.success(_("✅ Xác thực thành công.", "✅ Authentication successful."))

# -----------------------
# Location selection
locations = {
    "TP. Hồ Chí Minh": (10.762622, 106.660172),
    "Hà Nội": (21.028511, 105.804817),
    "Cần Thơ": (10.045161, 105.746857),
}
location_names = {k: _(k, k) for k in locations.keys()}  # Same names for now
selected_city_display = st.selectbox(_("📍 Chọn địa điểm:", "📍 Select location:"), list(location_names.values()))
selected_city = list(location_names.keys())[list(location_names.values()).index(selected_city_display)]
latitude, longitude = locations[selected_city]

# -----------------------
# Crop info
crops = {
    "Ngô": (75, 100),
    "Chuối": (270, 365),
    "Ớt": (70, 90),
}
crop_names = {k: _(k, k) for k in crops.keys()}

st.header(_("🌱 Quản lý cây trồng", "🌱 Crop Management"))

if user_type == _("Người điều khiển", "Control Administrator"):
    crop_select = st.selectbox(_("Chọn loại cây:", "Select crop type:"), list(crop_names.values()))
    crop_key = list(crop_names.keys())[list(crop_names.values()).index(crop_select)]
    planting_date = st.date_input(_("Ngày gieo trồng:", "Planting date:"), value=date.today())
    if st.button(_("💾 Lưu thông tin cây trồng", "💾 Save planting info")):
        crop_data[selected_city] = {"crop": crop_key, "planting_date": planting_date.isoformat()}
        save_json(DATA_FILE, crop_data)
        st.success(_("Đã lưu thông tin cây trồng.", "Crop info saved."))

if user_type == _("Người giám sát", "Monitoring Officer"):
    st.subheader(_("Thông tin cây trồng", "Crop Information"))
    info = crop_data.get(selected_city)
    if info:
        st.write(f"{_('Loại cây', 'Crop')}: {crop_names.get(info.get('crop'), '-')}")
        st.write(f"{_('Ngày gieo trồng', 'Planting date')}: {info.get('planting_date')}")
    else:
        st.info(_("Chưa có dữ liệu cây trồng cho khu vực này.", "No crop data for this location."))

# -----------------------
# Config system
st.header(_("⚙️ Cấu hình hệ thống", "⚙️ System Configuration"))
watering_schedule = config.get("watering_schedule", "06:00-08:00")
mode = config.get("mode", "auto")

if user_type == _("Người điều khiển", "Control Administrator"):
    start_time_str, end_time_str = watering_schedule.split("-")
    start_time = st.time_input(_("Giờ bắt đầu tưới:", "Start watering time:"), datetime.strptime(start_time_str, "%H:%M").time())
    end_time = st.time_input(_("Giờ kết thúc tưới:", "End watering time:"), datetime.strptime(end_time_str, "%H:%M").time())
    mode_select = st.radio(_("Chọn chế độ điều khiển:", "Select control mode:"), [_("Tự động", "Automatic"), _("Thủ công", "Manual")], index=0 if mode=="auto" else 1)

    if st.button(_("💾 Lưu cấu hình", "💾 Save configuration")):
        config["watering_schedule"] = f"{start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')}"
        config["mode"] = "auto" if mode_select == _("Tự động", "Automatic") else "manual"
        save_json(CONFIG_FILE, config)
        st.success(_("Đã lưu cấu hình.", "Configuration saved."))
else:
    st.write(f"{_('Khung giờ tưới:', 'Watering schedule:')} {watering_schedule}")
    st.write(f"{_('Chế độ:', 'Mode:')} {mode}")

# -----------------------
# Weather API (unchanged)
st.subheader(_("🌦️ Thời tiết hiện tại", "🌦️ Current Weather"))
weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}&current_weather=true"
try:
    response = requests.get(weather_url, timeout=10)
    response.raise_for_status()
    weather = response.json().get("current_weather", {})
except Exception as e:
    st.error(f"❌ {_('Lỗi khi tải dữ liệu thời tiết', 'Error loading weather data')}: {e}")
    weather = {}

st.write(f"{_('Nhiệt độ', 'Temperature')}: {weather.get('temperature', 'N/A')} °C")
st.write(f"{_('Tốc độ gió', 'Wind Speed')}: {weather.get('windspeed', 'N/A')} km/h")

# -----------------------
# Show connection status
if sensor_data["connected"]:
    st.success(_("✅ Đã kết nối với ESP32", "✅ Connected to ESP32"))
else:
    st.error(_("❌ Không kết nối được với ESP32", "❌ Cannot connect to ESP32"))

# -----------------------
# Show latest sensor data
st.subheader(_("📡 Dữ liệu cảm biến thực tế", "📡 Real sensor data"))
if sensor_data["soil_moisture"] is not None:
    st.write(f"{_('Độ ẩm đất', 'Soil Moisture')}: {sensor_data['soil_moisture']} %")
else:
    st.write(_("Không có dữ liệu độ ẩm đất", "No soil moisture data"))

if sensor_data["temperature"] is not None:
    st.write(f"{_('Nhiệt độ đất', 'Soil Temperature')}: {sensor_data['temperature']} °C")
else:
    st.write(_("Không có dữ liệu nhiệt độ đất", "No soil temperature data"))

if sensor_data["water_flow"] is not None:
    st.write(f"{_('Lưu lượng nước', 'Water Flow')}: {sensor_data['water_flow']} L/min")
else:
    st.write(_("Không có dữ liệu lưu lượng nước", "No water flow data"))

# -----------------------
# Manual pump control (only Control Administrator + manual mode)
if user_type == _("Người điều khiển", "Control Administrator") and mode == "manual":
    st.subheader(_("⚙️ Điều khiển bơm thủ công", "⚙️ Manual pump control"))
    if st.button(_("Bật bơm", "Turn ON pump")):
        # Send MQTT command
        try:
            mqtt_client = mqtt.Client()
            mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
            mqtt_client.publish(TOPIC_COMMAND, "pump_on")
            mqtt_client.disconnect()
            st.success(_("Đã gửi lệnh bật bơm.", "Pump ON command sent."))
        except Exception as e:
            st.error(_("Lỗi gửi lệnh bật bơm:", "Error sending pump ON command:") + str(e))

    if st.button(_("Tắt bơm", "Turn OFF pump")):
        try:
            mqtt_client = mqtt.Client()
            mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
            mqtt_client.publish(TOPIC_COMMAND, "pump_off")
            mqtt_client.disconnect()
            st.success(_("Đã gửi lệnh tắt bơm.", "Pump OFF command sent."))
        except Exception as e:
            st.error(_("Lỗi gửi lệnh tắt bơm:", "Error sending pump OFF command:") + str(e))

# -----------------------
# Save sensor data periodically (append to history and flow)
def save_sensor_history():
    if sensor_data["soil_moisture"] is not None and sensor_data["temperature"] is not None:
        # Append sensor history
        rec = {
            "timestamp": datetime.now(vn_tz).isoformat(),
            "sensor_hum": sensor_data["soil_moisture"],
            "sensor_temp": sensor_data["temperature"],
        }
        history = load_json(HISTORY_FILE, [])
        history.append(rec)
        save_json(HISTORY_FILE, history)

    if sensor_data["water_flow"] is not None:
        rec_flow = {
            "time": datetime.now(vn_tz).isoformat(),
            "flow": sensor_data["water_flow"]
        }
        flow = load_json(FLOW_FILE, [])
        flow.append(rec_flow)
        save_json(FLOW_FILE, flow)

# Call save sensor history (this runs each rerun, for real app should schedule differently)
save_sensor_history()

# -----------------------
# Show charts for sensor history
st.header(_("📊 Biểu đồ lịch sử độ ẩm, nhiệt độ, lưu lượng nước", "📊 Historical Charts"))

chart_date = st.date_input(_("Chọn ngày để xem dữ liệu", "Select date for chart"), value=date.today())

history_data = load_json(HISTORY_FILE, [])
flow_data = load_json(FLOW_FILE, [])

df_hist = pd.DataFrame(history_data)
df_flow = pd.DataFrame(flow_data)

if not df_hist.empty and not df_flow.empty:
    df_hist['timestamp'] = pd.to_datetime(df_hist['timestamp'], errors='coerce')
    df_hist['date'] = df_hist['timestamp'].dt.date
    df_day = df_hist[df_hist['date'] == chart_date]

    df_flow['time'] = pd.to_datetime(df_flow['time'], errors='coerce')
    df_flow['date'] = df_flow['time'].dt.date
    df_flow_day = df_flow[df_flow['date'] == chart_date]

    if not df_day.empty:
        fig, ax1 = plt.subplots(figsize=(12, 5))
        ax1.plot(df_day['timestamp'], df_day['sensor_hum'], 'b-', label=_("Độ ẩm đất", "Soil Moisture"))
        ax1.set_xlabel(_("Thời gian", "Time"))
        ax1.set_ylabel(_("Độ ẩm đất (%)", "Soil Moisture (%)"), color='b')
        ax1.tick_params(axis='y', labelcolor='b')

        ax2 = ax1.twinx()
        ax2.plot(df_day['timestamp'], df_day['sensor_temp'], 'r-', label=_("Nhiệt độ đất", "Soil Temperature"))
        ax2.set_ylabel(_("Nhiệt độ (°C)", "Temperature (°C)"), color='r')
        ax2.tick_params(axis='y', labelcolor='r')

        ax1.legend(loc='upper left')
        ax2.legend(loc='upper right')
        plt.title(_("Lịch sử độ ẩm đất và nhiệt độ", "Soil Moisture and Temperature History"))
        plt.xticks(rotation=45)
        plt.tight_layout()
        st.pyplot(fig)
    else:
        st.info(_("Không có dữ liệu độ ẩm và nhiệt độ trong ngày này.", "No soil moisture and temperature data for this day."))

    if not df_flow_day.empty:
        fig2, ax3 = plt.subplots(figsize=(12, 3))
        ax3.plot(df_flow_day['time'], df_flow_day['flow'], 'g-', label=_("Lưu lượng nước (L/min)", "Water Flow (L/min)"))
        ax3.set_xlabel(_("Thời gian", "Time"))
        ax3.set_ylabel(_("Lưu lượng nước (L/min)", "Water Flow (L/min)"), color='g')
        ax3.tick_params(axis='y', labelcolor='g')
        ax3.legend()
        plt.title(_("Lịch sử lưu lượng nước", "Water Flow History"))
        plt.xticks(rotation=45)
        plt.tight_layout()
        st.pyplot(fig2)
    else:
        st.info(_("Không có dữ liệu lưu lượng nước trong ngày này.", "No water flow data for this day."))
else:
    st.info(_("Chưa có dữ liệu lịch sử để hiển thị.", "No historical data to display."))

# -----------------------
# Footer
st.markdown("---")
st.caption("📡 API thời tiết: Open-Meteo | Dữ liệu cảm biến: ESP32-WROOM (MQTT)")
st.caption("Người thực hiện: Ngô Nguyễn Định Tường - Mai Phúc Khang")
