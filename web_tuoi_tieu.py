import streamlit as st
from datetime import datetime, timedelta, date, time
from PIL import Image
import json
import os
from streamlit_autorefresh import st_autorefresh
import pytz
import pandas as pd
import threading
import paho.mqtt.client as mqtt
import matplotlib.pyplot as plt

# --- Config ---
st.set_page_config(page_title="Smart Irrigation WebApp", layout="wide")
st_autorefresh(interval=60 * 1000, key="refresh")

# --- Localization ---
lang = st.sidebar.selectbox("🌐 Language / Ngôn ngữ", ["Tiếng Việt", "English"])
vi = lang == "Tiếng Việt"
def _(vi_text, en_text):
    return vi_text if vi else en_text

# --- File paths ---
DATA_FILE = "crop_data.json"
HISTORY_FILE = "history_irrigation.json"
FLOW_FILE = "flow_data.json"
CONFIG_FILE = "config.json"

# --- Timezone ---
vn_tz = pytz.timezone("Asia/Ho_Chi_Minh")

# --- Load/Save JSON helpers ---
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

# --- Data init ---
crop_data = load_json(DATA_FILE, {})
history_data = load_json(HISTORY_FILE, [])
flow_data = load_json(FLOW_FILE, [])
config = load_json(CONFIG_FILE, {"watering_schedule": "06:00-08:00", "mode": "auto"})

# --- MQTT Setup ---
MQTT_BROKER = "test.mosquitto.org"
MQTT_PORT = 1883
TOPIC_DATA = "smart_irrigation/sensor_data"
TOPIC_COMMAND = "smart_irrigation/command"

mqtt_client = mqtt.Client()

latest_soil_moisture = None
latest_soil_temp = None
latest_water_flow = None
pump_status_manual = False

mqtt_lock = threading.Lock()

def add_history_record(soil_moisture, soil_temp):
    now_iso = datetime.now(vn_tz).isoformat()
    rec = {"timestamp": now_iso, "soil_moisture": soil_moisture, "soil_temp": soil_temp}
    history = load_json(HISTORY_FILE, [])
    history.append(rec)
    save_json(HISTORY_FILE, history)

def add_flow_record(flow):
    now_iso = datetime.now(vn_tz).isoformat()
    rec = {"timestamp": now_iso, "flow": flow}
    flow_hist = load_json(FLOW_FILE, [])
    flow_hist.append(rec)
    save_json(FLOW_FILE, flow_hist)

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("MQTT connected")
        client.subscribe(TOPIC_DATA)
    else:
        print(f"MQTT connect failed with code {rc}")

def on_message(client, userdata, msg):
    global latest_soil_moisture, latest_soil_temp, latest_water_flow, pump_status_manual
    try:
        payload = msg.payload.decode()
        data = json.loads(payload)
        soil_moisture = data.get("soil_moisture")
        soil_temp = data.get("soil_temp")
        water_flow = data.get("water_flow")
        pump_manual = data.get("pump_manual", False)

        with mqtt_lock:
            if soil_moisture is not None:
                latest_soil_moisture = soil_moisture
            if soil_temp is not None:
                latest_soil_temp = soil_temp
            if water_flow is not None:
                latest_water_flow = water_flow
            pump_status_manual = pump_manual

        # Lưu lịch sử
        if soil_moisture is not None and soil_temp is not None:
            add_history_record(soil_moisture, soil_temp)
        if water_flow is not None:
            add_flow_record(water_flow)

    except Exception as e:
        print("MQTT message error:", e)

mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

def mqtt_thread():
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    mqtt_client.loop_forever()

threading.Thread(target=mqtt_thread, daemon=True).start()

# --- Helper để gửi lệnh bật/tắt bơm ---
def send_pump_command(turn_on):
    cmd = {"pump": "on" if turn_on else "off"}
    mqtt_client.publish(TOPIC_COMMAND, json.dumps(cmd))

# --- UI ---
st.title(_("🌾 Hệ thống tưới tiêu thông minh", "🌾 Smart Irrigation System"))

# --- Location and Crops ---
locations = {
    "TP. Hồ Chí Minh": (10.762622, 106.660172),
    "Hà Nội": (21.028511, 105.804817),
    "Cần Thơ": (10.045161, 105.746857),
    "Đà Nẵng": (16.054407, 108.202167),
}
location_names_vi = list(locations.keys())
location_names_en = ["Ho Chi Minh City", "Hanoi", "Can Tho", "Da Nang"]
location_display = st.selectbox(_("Chọn địa điểm", "Select location"), location_names_vi if vi else location_names_en)
selected_city = location_names_vi[location_names_en.index(location_display)] if not vi else location_display

# Crop list + thresholds độ ẩm đất tiêu chuẩn
crops = {
    "Ngô": 65,
    "Chuối": 70,
    "Ớt": 65,
}
crop_names_vi_en = {"Ngô": "Corn", "Chuối": "Banana", "Ớt": "Chili"}

# --- Crop selection ---
if st.checkbox(_("Chỉnh sửa thông tin trồng cây", "Edit crop planting info")):
    if selected_city not in crop_data:
        crop_data[selected_city] = {}
    crop_selected = st.selectbox(_("Chọn loại cây trồng", "Select crop type"), list(crops.keys()))
    planting_date = st.date_input(_("Ngày gieo trồng", "Planting date"), value=date.today())
    if st.button(_("Lưu thông tin cây trồng", "Save crop info")):
        crop_data[selected_city] = {"crop": crop_selected, "planting_date": planting_date.isoformat()}
        save_json(DATA_FILE, crop_data)
        st.success(_("Đã lưu thông tin cây trồng", "Crop info saved"))

# Hiển thị thông tin cây trồng hiện tại
if selected_city in crop_data:
    info = crop_data[selected_city]
    st.markdown(f"**{_('Loại cây:', 'Crop:')}** {info.get('crop', '---')}")
    st.markdown(f"**{_('Ngày gieo trồng:', 'Planting date:')}** {info.get('planting_date', '---')}")

# --- System Config: Mode and Schedule ---
st.header(_("Cấu hình hệ thống", "System Configuration"))
watering_schedule = config.get("watering_schedule", "06:00-08:00")
mode = config.get("mode", "auto")

col1, col2 = st.columns(2)
with col1:
    st.markdown(_("⏰ Khung giờ tưới nước", "Watering time window"))
    start_str, end_str = watering_schedule.split("-")
    start_time = st.time_input(_("Giờ bắt đầu", "Start time"), datetime.strptime(start_str, "%H:%M").time())
    end_time = st.time_input(_("Giờ kết thúc", "End time"), datetime.strptime(end_str, "%H:%M").time())
with col2:
    mode_option = st.radio(
        _("Chọn chế độ", "Select mode"),
        [_("Tự động", "Auto"), _("Thủ công", "Manual")],
        index=0 if mode == "auto" else 1,
    )

if st.button(_("Lưu cấu hình", "Save config")):
    config["watering_schedule"] = f"{start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')}"
    config["mode"] = "auto" if mode_option == _("Tự động", "Auto") else "manual"
    save_json(CONFIG_FILE, config)
    st.success(_("Đã lưu cấu hình.", "Config saved."))

# --- Helper check thời gian ---
def in_watering_time():
    now_t = datetime.now(vn_tz).time()
    s = datetime.strptime(config["watering_schedule"].split("-")[0], "%H:%M").time()
    e = datetime.strptime(config["watering_schedule"].split("-")[1], "%H:%M").time()
    if s <= e:
        return s <= now_t <= e
    else:
        # Qua nửa đêm
        return now_t >= s or now_t <= e

# --- Hiển thị dữ liệu cảm biến ---
st.header(_("Dữ liệu cảm biến thực tế", "Real Sensor Data"))

with mqtt_lock:
    soil_moist = latest_soil_moisture
    soil_temp = latest_soil_temp
    water_flow = latest_water_flow
    pump_manual_state = pump_status_manual

if soil_moist is None or soil_temp is None:
    st.warning(_("Chưa nhận được dữ liệu cảm biến từ ESP32.", "No sensor data received from ESP32 yet."))
else:
    st.metric(_("Độ ẩm đất hiện tại", "Current Soil Moisture"), f"{soil_moist:.1f}%")
    st.metric(_("Nhiệt độ đất hiện tại", "Current Soil Temperature"), f"{soil_temp:.1f}°C")

if water_flow is None:
    st.info(_("Chưa có dữ liệu lưu lượng nước.", "No water flow data yet."))
else:
    st.metric(_("Lưu lượng nước hiện tại", "Current Water Flow"), f"{water_flow:.1f} L/min")

st.markdown(f"**{_('Trạng thái bơm thủ công', 'Manual Pump Status')}:** {'ON' if pump_manual_state else 'OFF'}")

# --- Biểu đồ lịch sử ---
st.header(_("Lịch sử cảm biến theo ngày", "Sensor History by Date"))

# Chọn ngày
hist_df = pd.DataFrame(history_data)
flow_df = pd.DataFrame(flow_data)

if not hist_df.empty:
    hist_df["timestamp"] = pd.to_datetime(hist_df["timestamp"]).dt.tz_convert(vn_tz)
if not flow_df.empty:
    flow_df["timestamp"] = pd.to_datetime(flow_df["timestamp"]).dt.tz_convert(vn_tz)

selected_date = st.date_input(_("Chọn ngày xem lịch sử", "Select date to view history"), value=date.today())

def filter_by_date(df, date_col, selected_date):
    if df.empty:
        return df
    mask = (df[date_col].dt.date == selected_date)
    return df.loc[mask]

hist_day = filter_by_date(hist_df, "timestamp", selected_date)
flow_day = filter_by_date(flow_df, "timestamp", selected_date)

if hist_day.empty and flow_day.empty:
    st.info(_("Không có dữ liệu trong ngày này.", "No data for this date."))
else:
    fig, axs = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
    if not hist_day.empty:
        axs[0].plot(hist_day["timestamp"], hist_day["soil_moisture"], label=_("Độ ẩm đất", "Soil Moisture"), color="blue")
        axs[0].set_ylabel("%")
        axs[0].set_title(_("Độ ẩm đất theo thời gian", "Soil Moisture over Time"))
        axs[0].legend()
        axs[1].plot(hist_day["timestamp"], hist_day["soil_temp"], label=_("Nhiệt độ đất", "Soil Temperature"), color="red")
        axs[1].set_ylabel("°C")
        axs[1].set_title(_("Nhiệt độ đất theo thời gian", "Soil Temperature over Time"))
        axs[1].legend()
    else:
        axs[0].text(0.5, 0.5, _("Không có dữ liệu độ ẩm đất", "No soil moisture data"), ha='center')
        axs[1].text(0.5, 0.5, _("Không có dữ liệu nhiệt độ đất", "No soil temperature data"), ha='center')

    if not flow_day.empty:
        axs[2].plot(flow_day["timestamp"], flow_day["flow"], label=_("Lưu lượng nước", "Water Flow"), color="green")
        axs[2].set_ylabel("L/min")
        axs[2].set_title(_("Lưu lượng nước theo thời gian", "Water Flow over Time"))
        axs[2].legend()
    else:
        axs[2].text(0.5, 0.5, _("Không có dữ liệu lưu lượng nước", "No water flow data"), ha='center')

    plt.xlabel(_("Thời gian", "Time"))
    plt.tight_layout()
    st.pyplot(fig)

# --- Quyết định bật bơm tự động ---
st.header(_("Điều khiển bơm", "Pump Control"))

if selected_city in crop_data:
    crop_info = crop_data[selected_city]
    crop_name = crop_info.get("crop")
else:
    crop_name = None

threshold = crops.get(crop_name, 65)  # ngưỡng chuẩn độ ẩm đất cho cây
st.markdown(f"{_('Loại cây đang trồng', 'Current crop')}: **{crop_name or _('Chưa chọn', 'Not selected')}**")
st.markdown(f"{_('Ngưỡng độ ẩm đất tiêu chuẩn', 'Soil moisture threshold')}: **{threshold}%**")

auto_pump_on = False
pump_msg = ""

if mode == "auto":
    if in_watering_time():
        if soil_moist is not None and soil_moist < (threshold - 10):
            auto_pump_on = True
            pump_msg = _("Độ ẩm đất thấp hơn ngưỡng, sẽ tự động bật bơm.", "Soil moisture below threshold, pump will auto ON.")
        else:
            pump_msg = _("Độ ẩm đất đạt hoặc trên ngưỡng, không bật bơm.", "Soil moisture adequate, pump remains OFF.")
    else:
        pump_msg = _("Ngoài khung giờ tưới, không bật bơm.", "Outside watering schedule, pump remains OFF.")
else:
    pump_msg = _("Chế độ thủ công: Không tự động điều khiển bơm.", "Manual mode: No automatic pump control.")

st.info(pump_msg)

if mode == "auto":
    # Gửi lệnh MQTT tự động
    send_pump_command(auto_pump_on)
    st.markdown(f"**{_('Lệnh gửi bơm tự động', 'Auto pump command sent')}:** {'ON' if auto_pump_on else 'OFF'}")
else:
    st.markdown(f"**{_('Chế độ thủ công: người dùng bật/tắt bơm trực tiếp tại tủ điện.', 'Manual mode: Pump controlled manually at cabinet.')}")
    st.markdown(f"**{_('Trạng thái bơm thủ công hiện tại', 'Current manual pump status')}:** {'ON' if pump_manual_state else 'OFF'}")

# --- Kết thúc ---
st.markdown("---")
st.markdown(_("© 2025 - Hệ thống tưới tiêu thông minh - Smart Irrigation System", "© 2025 - Smart Irrigation System"))

