# web_esp.py
import streamlit as st
from datetime import datetime, timedelta, date, time
from PIL import Image
import requests
import json
import os
from streamlit_autorefresh import st_autorefresh
import pytz
import pandas as pd
import paho.mqtt.client as mqtt
import threading

# Thông số MQTT broker và topic điều khiển bơm
MQTT_BROKER = "broker.hivemq.com"  # hoặc IP broker của bạn
MQTT_PORT = 1883
MQTT_TOPIC_PUMP = "esp32/pump/control"
MQTT_TOPIC_SENSOR = "esp32/sensor/data"

sensor_data = None  # lưu dữ liệu cảm biến nhận được qua MQTT

def send_mqtt_command(message):
    try:
        client = mqtt.Client()
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.publish(MQTT_TOPIC_PUMP, message)
        client.disconnect()
        return True
    except Exception as e:
        st.error(f"Lỗi gửi lệnh MQTT: {e}")
        return False

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("MQTT connected successfully")
        client.subscribe(MQTT_TOPIC_SENSOR)
    else:
        print("MQTT connect failed with code", rc)

def on_message(client, userdata, msg):
    global sensor_data
    try:
        payload = msg.payload.decode("utf-8")
        data = json.loads(payload)
        sensor_data = data
        print(f"Received sensor data: {sensor_data}")
    except Exception as e:
        print("Error parsing MQTT message:", e)

def mqtt_thread():
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_forever()

# Khởi chạy MQTT client trong thread nền
threading.Thread(target=mqtt_thread, daemon=True).start()

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
if "moisture_thresholds" not in config:
    config["moisture_thresholds"] = {"Ngô": 65, "Chuối": 70, "Ớt": 65}
moisture_thresholds = config["moisture_thresholds"]

# timezone
vn_tz = pytz.timezone("Asia/Ho_Chi_Minh")
now = datetime.now(vn_tz)

# -----------------------
# UI - Header & Logo
# -----------------------
try:
    st.markdown("""
    <style>
    .block-container { padding-top: 1rem; }
    h3 { color: #000000 !important; font-size: 20px !important; font-family: Arial, sans-serif !important; font-weight: bold !important; }
    .led { display:inline-block; width:14px; height:14px; border-radius:50%; margin-right:6px; }
    </style>
    """, unsafe_allow_html=True)
    st.image(Image.open("logo1.png"), width=1200)
except:
    st.warning(_("❌ Không tìm thấy logo.png", "❌ logo.png not found"))

st.markdown(f"<h2 style='text-align: center; font-size: 50px;'>🌾 { _('Hệ thống tưới tiêu nông nghiệp thông minh', 'Smart Agricultural Irrigation System') } 🌾</h2>", unsafe_allow_html=True)
st.markdown(f"<h3>⏰ { _('Thời gian hiện tại', 'Current time') }: {now.strftime('%d/%m/%Y')}</h3>", unsafe_allow_html=True)

# -----------------------
# Sidebar - role, auth
# -----------------------
st.sidebar.title(_("🔐 Chọn vai trò người dùng", "🔐 Select User Role"))
user_type = st.sidebar.radio(_("Bạn là:", "You are:"), [_("Người điều khiển", "Control Administrator"), _("Người giám sát", " Monitoring Officer")])

if user_type == _("Người điều khiển", "Control Administrator"):
    password = st.sidebar.text_input(_("🔑 Nhập mật khẩu:", "🔑 Enter password:"), type="password")
    if password != "admin123":
        st.sidebar.error(_("❌ Mật khẩu sai. Truy cập bị từ chối.", "❌ Incorrect password. Access denied."))
        st.stop()
    else:
        st.sidebar.success(_("✅ Xác thực thành công.", "✅ Authentication successful."))

# -----------------------
# Locations & crops (thêm đoạn lấy tọa độ)
# -----------------------
locations = {
    "TP. Hồ Chí Minh": (10.762622, 106.660172),
    "Hà Nội": (21.028511, 105.804817),
    "Cần Thơ": (10.045161, 105.746857),
    "Đà Nẵng": (16.054407, 108.202167),
    "Bình Dương": (11.3254, 106.4770),
    "Đồng Nai": (10.9453, 106.8133),
}
location_names = {
    "TP. Hồ Chí Minh": _("TP. Hồ Chí Minh", "Ho Chi Minh City"),
    "Hà Nội": _("Hà Nội", "Hanoi"),
    "Cần Thơ": _("Cần Thơ", "Can Tho"),
    "Đà Nẵng": _("Đà Nẵng", "Da Nang"),
    "Bình Dương": _("Bình Dương", "Binh Duong"),
    "Đồng Nai": _("Đồng Nai", "Dong Nai")
}
location_display_names = [location_names[k] for k in locations.keys()]
selected_city_display = st.selectbox(_("📍 Chọn địa điểm:", "📍 Select location:"), location_display_names)
selected_city = next(k for k, v in location_names.items() if v == selected_city_display)
latitude, longitude = locations[selected_city]

# -----------------------
# Weather API
# -----------------------
st.subheader(_("🌦️ Thời tiết hiện tại", "🌦️ Current Weather"))
weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}&current=temperature_2m,relative_humidity_2m,precipitation,precipitation_probability&timezone=auto"
try:
    response = requests.get(weather_url, timeout=10)
    response.raise_for_status()
    weather_data = response.json()
    current_weather = weather_data.get("current", {})
except Exception as e:
    st.error(f"❌ {_('Lỗi khi tải dữ liệu thời tiết', 'Error loading weather data')}: {str(e)}")
    current_weather = {"temperature_2m": "N/A", "relative_humidity_2m": "N/A", "precipitation": "N/A", "precipitation_probability": "N/A"}

col1, col2, col3 = st.columns(3)
col1.metric("🌡️ " + _("Nhiệt độ", "Temperature"), f"{current_weather.get('temperature_2m', 'N/A')} °C")
col2.metric("💧 " + _("Độ ẩm", "Humidity"), f"{current_weather.get('relative_humidity_2m', 'N/A')} %")
col3.metric("☔ " + _("Khả năng mưa", "Precipitation Probability"), f"{current_weather.get('precipitation_probability', 'N/A')} %")

# -----------------------
# Sensor data from ESP32 (MQTT real data)
# -----------------------
st.subheader(_("📡 Dữ liệu cảm biến thực tế (ESP32)", "📡 Real sensor data (ESP32)"))

if sensor_data:
    soil_moisture = sensor_data.get("soil_moisture")
    soil_temp = sensor_data.get("soil_temp")
    light_level = sensor_data.get("light")
    water_flow = sensor_data.get("water_flow")

    st.write(f"- {_('Độ ẩm đất hiện tại', 'Current soil moisture')}: {soil_moisture} %")
    st.write(f"- {_('Nhiệt độ đất', 'Soil temperature')}: {soil_temp} °C")
    st.write(f"- {_('Cường độ ánh sáng', 'Light intensity')}: {light_level} lux")
    st.write(f"- {_('Lưu lượng nước', 'Water flow')}: {water_flow} L/min")

    # Lưu dữ liệu mới vào lịch sử
    if soil_moisture is not None and soil_temp is not None:
        add_history_record(soil_moisture, soil_temp)
    if water_flow is not None:
        add_flow_record(water_flow)
else:
    st.info(_("Chưa có dữ liệu cảm biến thực tế từ ESP32.", "No real sensor data from ESP32 yet."))
    soil_moisture = None

# -----------------------
# Tưới nước - Logic quyết định
# -----------------------
st.header(_("🚰 Điều khiển tưới nước", "🚰 Irrigation Control"))

watering_start_str, watering_end_str = config["watering_schedule"].split("-")
watering_start = datetime.combine(date.today(), datetime.strptime(watering_start_str, "%H:%M").time())
watering_end = datetime.combine(date.today(), datetime.strptime(watering_end_str, "%H:%M").time())
now_time = datetime.now(vn_tz).replace(tzinfo=None)

is_in_watering_time = watering_start <= now_time <= watering_end

# Lấy cây trồng đầu tiên trong khu vực để lấy ngưỡng
selected_crop_for_decision = None
if selected_city in crop_data and crop_data[selected_city].get("plots"):
    selected_crop_for_decision = crop_data[selected_city]["plots"][0]["crop"]

threshold = config.get("moisture_thresholds", {}).get(selected_crop_for_decision, 65) if selected_crop_for_decision else 65

mode_flag = config.get("mode", "auto")

if soil_moisture is not None:
    should_water = soil_moisture < threshold and mode_flag == "auto" and is_in_watering_time
else:
    should_water = False
    st.warning(_("Không có dữ liệu độ ẩm đất để quyết định tưới.", "No soil moisture data for irrigation decision."))

st.write(f"- {_('Ngưỡng độ ẩm đất cần tưới cho cây', 'Soil moisture threshold for crop')}: {threshold} %")
st.write(f"- {_('Khung giờ tưới nước hiện tại', 'Current watering time window')}: {config['watering_schedule']}")
st.write(f"- {_('Thời gian hiện tại', 'Current time')}: {now_time.strftime('%H:%M:%S')}")
st.write(f"- {_('Nhu cầu tưới', 'Watering needed')}: {'✅' if should_water else '❌'}")

# 5 phút chờ xác nhận bật bơm
if should_water:
    if user_type == _("Người điều khiển", "Control Administrator"):
        st.warning(_("🌊 Cần bật bơm trong 5 phút tới, vui lòng xác nhận", "🌊 Pump should be turned ON in next 5 minutes, please confirm"))
        col_yes, col_no = st.columns(2)
        with col_yes:
            if st.button(_("✅ Đồng ý bật bơm", "✅ Confirm turn ON pump")):
                if send_mqtt_command("PUMP_ON"):
                    st.success(_("Đã gửi lệnh bật bơm.", "Pump ON command sent."))
        with col_no:
            if st.button(_("❌ Không bật bơm", "❌ Cancel pump ON")):
                st.info(_("Bơm sẽ không được bật.", "Pump will NOT be turned on."))
        # Nếu không xác nhận sau 5 phút (cần bạn bổ sung logic thời gian chờ 5 phút phía backend hoặc xử lý ngoài)
    else:
        st.info(_("Chỉ người điều khiển mới có thể bật bơm.", "Only controller can turn ON pump."))

else:
    st.info(_("Không cần tưới vào lúc này.", "No irrigation needed now."))

# -----------------------
# Lịch sử tưới
# -----------------------
st.header(_("📅 Lịch sử tưới nước", "📅 Irrigation History"))

history = load_json(HISTORY_FILE, [])
if history:
    df_hist = pd.DataFrame(history)
    df_hist["timestamp"] = pd.to_datetime(df_hist["timestamp"])
    df_hist = df_hist.sort_values(by="timestamp", ascending=False)
    st.dataframe(df_hist)
else:
    st.info(_("Chưa có lịch sử tưới.", "No irrigation history."))

# -----------------------
# Lưu file và kết thúc
# -----------------------

st.markdown("---")
st.caption("📡 API thời tiết: Open-Meteo | Dữ liệu cảm biến: ESP32-WROOM (MQTT real data)")
st.caption("Người thực hiện: Ngô Nguyễn Định Tường-Mai Phúc Khang")
