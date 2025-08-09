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

# ----------------------
# CẤU HÌNH CHUNG
# ----------------------
st.set_page_config(page_title="Smart Irrigation WebApp", layout="wide")

# Thời gian Việt Nam
VN_TZ = pytz.timezone("Asia/Ho_Chi_Minh")

# MQTT server (bạn thay nếu cần)
MQTT_BROKER = "test.mosquitto.org"
MQTT_PORT = 1883
TOPIC_SENSOR = "smart_irrigation/sensor_data"
TOPIC_COMMAND = "smart_irrigation/command"

# File lưu dữ liệu
DATA_FILE = "crop_data.json"
HISTORY_FILE = "history_data.json"
CONFIG_FILE = "config.json"

# ----------------------
# HÀM TIỆN ÍCH
# ----------------------
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

# ----------------------
# HỖ TRỢ NGÔN NGỮ (Việt - Anh)
# ----------------------
lang = st.sidebar.selectbox("🌐 Language / Ngôn ngữ", ["Tiếng Việt", "English"])
VI = lang == "Tiếng Việt"

def _(vi_text, en_text):
    return vi_text if VI else en_text

# ----------------------
# DỮ LIỆU CẢM BIẾN - Toàn cục
# ----------------------
sensor_data = {
    "soil_moisture": None,
    "temperature": None,
    "water_flow": None,
    "last_update": None,
    "connected": False,
}

# ----------------------
# MQTT CLIENT
# ----------------------
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
        # Cập nhật dữ liệu cảm biến nhận được
        sensor_data["soil_moisture"] = data.get("soil_moisture", None)
        sensor_data["temperature"] = data.get("temperature", None)
        sensor_data["water_flow"] = data.get("water_flow", None)
        sensor_data["last_update"] = datetime.now(VN_TZ)
    except Exception as e:
        print(f"MQTT msg error: {e}")

def mqtt_loop():
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_forever()
    except Exception as e:
        print(f"MQTT connect failed: {e}")
        sensor_data["connected"] = False

# Khởi động MQTT thread chạy nền
mqtt_thread = threading.Thread(target=mqtt_loop, daemon=True)
mqtt_thread.start()

# ----------------------
# LOAD DỮ LIỆU LƯU TRỮ
# ----------------------
crop_data = load_json(DATA_FILE, {})
history_data = load_json(HISTORY_FILE, [])
config = load_json(CONFIG_FILE, {"watering_schedule": "06:00-08:00", "mode": "auto"})

# ----------------------
# GIAO DIỆN CHÍNH
# ----------------------
st.title(_("🌾 Hệ thống tưới tiêu nông nghiệp thông minh", "🌾 Smart Agricultural Irrigation System"))
st.markdown(f"<p style='text-align:center'>{_('Thời gian hiện tại', 'Current time')}: {datetime.now(VN_TZ).strftime('%d/%m/%Y %H:%M:%S')}</p>", unsafe_allow_html=True)

# --- Chọn vai trò người dùng ---
st.sidebar.title(_("🔐 Chọn vai trò người dùng", "🔐 Select User Role"))
role = st.sidebar.radio(_("Bạn là:", "You are:"), [_("Người điều khiển", "Control Administrator"), _("Người giám sát", "Monitoring Officer")])

if role == _("Người điều khiển", "Control Administrator"):
    pwd = st.sidebar.text_input(_("🔑 Nhập mật khẩu:", "🔑 Enter password:"), type="password")
    if pwd != "admin123":
        st.sidebar.error(_("❌ Mật khẩu sai. Truy cập bị từ chối.", "❌ Wrong password. Access denied."))
        st.stop()
    else:
        st.sidebar.success(_("✅ Xác thực thành công.", "✅ Authentication successful."))

# --- Chọn địa điểm ---
locations = {
    "TP. Hồ Chí Minh": (10.762622, 106.660172),
    "Hà Nội": (21.028511, 105.804817),
    "Cần Thơ": (10.045161, 105.746857),
}
loc_display = {k: _(k, k) for k in locations.keys()}
city_display = st.selectbox(_("📍 Chọn địa điểm:", "📍 Select location:"), list(loc_display.values()))
city = list(loc_display.keys())[list(loc_display.values()).index(city_display)]
lat, lon = locations[city]

# --- Quản lý cây trồng ---
crops = {
    "Ngô": (75, 100),
    "Chuối": (270, 365),
    "Ớt": (70, 90),
}
crop_display = {k: _(k, k) for k in crops.keys()}

st.header(_("🌱 Quản lý cây trồng", "🌱 Crop Management"))

if role == _("Người điều khiển", "Control Administrator"):
    selected_crop_display = st.selectbox(_("Chọn loại cây:", "Select crop:"), list(crop_display.values()))
    selected_crop = list(crop_display.keys())[list(crop_display.values()).index(selected_crop_display)]
    planting_date = st.date_input(_("Ngày gieo trồng:", "Planting date:"), value=date.today())

    if st.button(_("💾 Lưu thông tin cây trồng", "💾 Save crop info")):
        crop_data[city] = {"crop": selected_crop, "planting_date": planting_date.isoformat()}
        save_json(DATA_FILE, crop_data)
        st.success(_("Đã lưu thông tin cây trồng.", "Crop info saved."))

elif role == _("Người giám sát", "Monitoring Officer"):
    st.subheader(_("Thông tin cây trồng", "Crop Info"))
    info = crop_data.get(city)
    if info:
        st.write(f"{_('Loại cây', 'Crop')}: {crop_display.get(info.get('crop'), '-')}")
        st.write(f"{_('Ngày gieo trồng', 'Planting date')}: {info.get('planting_date')}")
    else:
        st.info(_("Chưa có dữ liệu cây trồng cho khu vực này.", "No crop data for this location."))

# --- Cấu hình hệ thống ---
st.header(_("⚙️ Cấu hình hệ thống", "⚙️ System Configuration"))
water_schedule = config.get("watering_schedule", "06:00-08:00")
mode = config.get("mode", "auto")

if role == _("Người điều khiển", "Control Administrator"):
    start_str, end_str = water_schedule.split("-")
    start_time = st.time_input(_("Giờ bắt đầu tưới:", "Start watering time:"), datetime.strptime(start_str, "%H:%M").time())
    end_time = st.time_input(_("Giờ kết thúc tưới:", "End watering time:"), datetime.strptime(end_str, "%H:%M").time())
    mode_select = st.radio(_("Chọn chế độ điều khiển:", "Select control mode:"), [_("Tự động", "Automatic"), _("Thủ công", "Manual")], index=0 if mode=="auto" else 1)

    if st.button(_("💾 Lưu cấu hình", "💾 Save configuration")):
        config["watering_schedule"] = f"{start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')}"
        config["mode"] = "auto" if mode_select == _("Tự động", "Automatic") else "manual"
        save_json(CONFIG_FILE, config)
        st.success(_("Đã lưu cấu hình.", "Configuration saved."))

else:
    st.write(f"{_('Khung giờ tưới:', 'Watering schedule:')} {water_schedule}")
    st.write(f"{_('Chế độ:', 'Mode:')} {mode}")

# --- Hiển thị trạng thái MQTT ---
st.subheader(_("📡 Trạng thái kết nối ESP32", "📡 ESP32 connection status"))
if sensor_data["connected"]:
    st.success(_("✅ Đã kết nối với ESP32", "✅ Connected to ESP32"))
else:
    st.error(_("❌ Không kết nối được với ESP32", "❌ Cannot connect to ESP32"))

# --- Hiển thị dữ liệu cảm biến real-time ---
st.subheader(_("📊 Dữ liệu cảm biến thực tế", "📊 Real-time sensor data"))

soil_moisture = sensor_data.get("soil_moisture")
temperature = sensor_data.get("temperature")
water_flow = sensor_data.get("water_flow")
last_update = sensor_data.get("last_update")

if soil_moisture is not None:
    st.write(f"{_('Độ ẩm đất:', 'Soil Moisture:')} {soil_moisture} %")
else:
    st.write(_("Không có dữ liệu độ ẩm đất", "No soil moisture data"))

if temperature is not None:
    st.write(f"{_('Nhiệt độ đất:', 'Soil Temperature:')} {temperature} °C")
else:
    st.write(_("Không có dữ liệu nhiệt độ đất", "No soil temperature data"))

if water_flow is not None:
    st.write(f"{_('Lưu lượng nước:', 'Water Flow:')} {water_flow} L/min")
else:
    st.write(_("Không có dữ liệu lưu lượng nước", "No water flow data"))

if last_update:
    st.write(f"{_('Cập nhật lúc:', 'Last updated at:')} {last_update.strftime('%H:%M:%S')}")

# --- Điều khiển bơm thủ công (chỉ Người điều khiển & chế độ thủ công) ---
if role == _("Người điều khiển", "Control Administrator") and mode == "manual":
    st.header(_("⚙️ Điều khiển bơm thủ công", "⚙️ Manual pump control"))

    def send_mqtt_command(cmd):
        try:
            client = mqtt.Client()
            client.connect(MQTT_BROKER, MQTT_PORT, 60)
            client.publish(TOPIC_COMMAND, cmd)
            client.disconnect()
            st.success(_("Đã gửi lệnh: ", "Command sent: ") + cmd)
        except Exception as e:
            st.error(_("Lỗi gửi lệnh:", "Error sending command: ") + str(e))

    col1, col2 = st.columns(2)
    with col1:
        if st.button(_("Bật bơm", "Turn ON pump")):
            send_mqtt_command("pump_on")
    with col2:
        if st.button(_("Tắt bơm", "Turn OFF pump")):
            send_mqtt_command("pump_off")

# --- Lưu lịch sử dữ liệu cảm biến (mỗi lần chạy app) ---
def save_history():
    global history_data
    if soil_moisture is not None and temperature is not None:
        history_data.append({
            "timestamp": datetime.now(VN_TZ).isoformat(),
            "soil_moisture": soil_moisture,
            "temperature": temperature,
            "water_flow": water_flow,
        })
        # Giới hạn lịch sử trong 7 ngày (tối đa 1000 bản ghi)
        cutoff = datetime.now(VN_TZ) - timedelta(days=7)
        history_data = [h for h in history_data if datetime.fromisoformat(h["timestamp"]) > cutoff]
        save_json(HISTORY_FILE, history_data)

save_history()

# --- Biểu đồ lịch sử dữ liệu ---
st.header(_("📈 Biểu đồ lịch sử dữ liệu", "📈 Historical Data Charts"))

selected_date = st.date_input(_("Chọn ngày xem dữ liệu", "Select date"), value=date.today())

# Tạo dataframe từ lịch sử
df = pd.DataFrame(history_data)
if not df.empty:
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["date"] = df["timestamp"].dt.date

    df_day = df[df["date"] == selected_date]

    if not df_day.empty:
        fig, ax1 = plt.subplots(figsize=(12,5))

        ax1.plot(df_day["timestamp"], df_day["soil_moisture"], 'b-', label=_("Độ ẩm đất (%)", "Soil Moisture (%)"))
        ax1.set_xlabel(_("Thời gian", "Time"))
        ax1.set_ylabel(_("Độ ẩm đất (%)", "Soil Moisture (%)"), color='b')
        ax1.tick_params(axis='y', labelcolor='b')

        ax2 = ax1.twinx()
        ax2.plot(df_day["timestamp"], df_day["temperature"], 'r-', label=_("Nhiệt độ (°C)", "Temperature (°C)"))
        ax2.set_ylabel(_("Nhiệt độ (°C)", "Temperature (°C)"), color='r')
        ax2.tick_params(axis='y', labelcolor='r')

        plt.title(_("Lịch sử độ ẩm đất và nhiệt độ", "Soil Moisture and Temperature History"))
        ax1.legend(loc='upper left')
        ax2.legend(loc='upper right')
        plt.xticks(rotation=45)
        plt.tight_layout()
        st.pyplot(fig)
    else:
        st.info(_("Không có dữ liệu cho ngày này.", "No data for this day."))
else:
    st.info(_("Chưa có dữ liệu lịch sử.", "No historical data available."))

# --- API Thời tiết ---
st.header(_("🌦️ Thời tiết hiện tại", "🌦️ Current Weather"))

weather_api_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"

try:
    res = requests.get(weather_api_url, timeout=5)
    res.raise_for_status()
    weather_json = res.json()
    current_weather = weather_json.get("current_weather", {})
except Exception as e:
    st.error(_("Lỗi lấy dữ liệu thời tiết:", "Error fetching weather data:") + str(e))
    current_weather = {}

if current_weather:
    st.write(f"{_('Nhiệt độ', 'Temperature')}: {current_weather.get('temperature', 'N/A')} °C")
    st.write(f"{_('Tốc độ gió', 'Wind speed')}: {current_weather.get('windspeed', 'N/A')} km/h")
else:
    st.info(_("Không có dữ liệu thời tiết.", "No weather data."))

# ----------------------
# Footer
# ----------------------
st.markdown("---")
st.caption("📡 API thời tiết: Open-Meteo | Dữ liệu cảm biến: ESP32-WROOM (MQTT)")
st.caption("Người thực hiện: Ngô Nguyễn Định Tường - Mai Phúc Khang")
