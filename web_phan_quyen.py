# web_esp.py
# Smart Irrigation Streamlit app (MQTT) - Updated to only send configuration (watering slots, mode, thresholds)
# ESP32 should handle pump ON/OFF locally based on received config. Web app only displays pump status indicator.

import streamlit as st
from datetime import datetime, timedelta, date, time
import threading
from PIL import Image
import requests
import json
import os
from streamlit_autorefresh import st_autorefresh
import pytz
import pandas as pd
import paho.mqtt.client as mqtt

# -----------------------
# Timezone (used by helpers)
# -----------------------
vn_tz = pytz.timezone("Asia/Ho_Chi_Minh")

# -----------------------
# MQTT & sensor state
# -----------------------
sensor_data = None  # biến toàn cục lưu dữ liệu sensor nhận được

MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_TOPIC_SENSOR = "esp32/sensor/data"
MQTT_TOPIC_CONFIG = "esp32/config/update"  # topic to publish configuration updates to ESP32

# Hàm gửi cấu hình MQTT (tạo client mỗi lần để đơn giản)
def send_config_to_esp32(config_data):
    try:
        client = mqtt.Client()
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        payload = json.dumps(config_data)
        client.publish(MQTT_TOPIC_CONFIG, payload)
        client.disconnect()
        return True
    except Exception as e:
        st.error(f"Lỗi gửi cấu hình MQTT: {e}")
        return False

# MQTT callbacks
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
        # expected payload example:
        # {"soil_moisture":45, "soil_temp":28.5, "light":400, "water_flow":2.3, "pump_status":"ON"}
        sensor_data = data
        print(f"Received sensor data: {sensor_data}")
    except Exception as e:
        print("Error parsing MQTT message:", e)


def mqtt_thread():
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_forever()
    except Exception as e:
        print("MQTT thread error:", e)

# Khởi chạy MQTT client trong thread riêng
threading.Thread(target=mqtt_thread, daemon=True).start()

# -----------------------
# Config & helpers
# -----------------------
st.set_page_config(page_title="Smart Irrigation WebApp", layout="wide")
st_autorefresh(interval=60 * 1000, key="init_refresh")
st.markdown("""
    <style>
        label, .stSelectbox label, .stDateInput label, .stTimeInput label, .stRadio label, .stNumberInput label {
            font-size: 20px !important;
            font-weight: bold !important;
        }
        .led { display:inline-block; width:14px; height:14px; border-radius:50%; margin-right:6px; }
    </style>
""", unsafe_allow_html=True)

# --- I18N ---
lang = st.sidebar.selectbox("🌐 Language / Ngôn ngữ", ["Tiếng Việt", "English"])
vi = lang == "Tiếng Việt"

def _(vi_text, en_text):
    return vi_text if vi else en_text

def big_label(vi_text, en_text, size=18):
    text = _(vi_text, en_text)
    return f"<span style='font-size:{size}px; font-weight:700'>{text}</span>"

# Files
DATA_FILE = "crop_data.json"
HISTORY_FILE = "history_irrigation.json"   # lưu lịch sử sensor + tưới
FLOW_FILE = "flow_data.json"
CONFIG_FILE = "config.json"


def load_json(path, default=None):
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
    # giữ tối đa 1 năm: xoá record cũ hơn 365 ngày
    cutoff = datetime.now(vn_tz) - timedelta(days=365)
    filtered = []
    for r in history:
        try:
            t = datetime.fromisoformat(r.get("timestamp"))
            if t >= cutoff:
                filtered.append(r)
        except:
            filtered.append(r)
    save_json(HISTORY_FILE, filtered)

# Hàm thêm record lưu lượng vào flow_data
def add_flow_record(flow_val):
    now_iso = datetime.now(vn_tz).isoformat()
    new_record = {
        "time": now_iso,
        "flow": flow_val
    }
    flow = load_json(FLOW_FILE, [])
    flow.append(new_record)
    # giữ 1 năm
    cutoff = datetime.now(vn_tz) - timedelta(days=365)
    filtered = []
    for r in flow:
        try:
            t = datetime.fromisoformat(r.get("time"))
            if t >= cutoff:
                filtered.append(r)
        except:
            filtered.append(r)
    save_json(FLOW_FILE, filtered)

# Hàm thêm lịch sử hành động tưới (chỉ ghi sự kiện hệ thống tự đánh dấu, không gửi lệnh nữa)
def add_irrigation_action(action, area=None, crop=None):
    now_iso = datetime.now(vn_tz).isoformat()
    rec = {
        "timestamp": now_iso,
        "action": action,  # descriptive action string
        "area": area,
        "crop": crop
    }
    history = load_json(HISTORY_FILE, [])
    history.append(rec)
    # filter 1 year
    cutoff = datetime.now(vn_tz) - timedelta(days=365)
    filtered = []
    for r in history:
        try:
            t = datetime.fromisoformat(r.get("timestamp"))
            if t >= cutoff:
                filtered.append(r)
        except:
            filtered.append(r)
    save_json(HISTORY_FILE, filtered)

# Load persistent data
crop_data = load_json(DATA_FILE, {}) or {}
history_data = load_json(HISTORY_FILE, []) or []
flow_data = load_json(FLOW_FILE, []) or []
config = load_json(CONFIG_FILE, {
    "watering_slots": [{"start": "06:00", "end": "08:00"}],
    "mode": "auto",
    "moisture_thresholds": {"Ngô": 65, "Chuối": 70, "Ớt": 65}
}) or {}

# ensure keys
if "moisture_thresholds" not in config:
    config["moisture_thresholds"] = {"Ngô": 65, "Chuối": 70, "Ớt": 65}
if "watering_slots" not in config:
    config["watering_slots"] = [{"start": "06:00", "end": "08:00"}]

now = datetime.now(vn_tz)

# -----------------------
# UI - Header & Logo
# -----------------------
try:
    if os.path.exists("logo1.png"):
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
# Locations & crops (unchanged)
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
st.markdown(
    f"<label style='font-size:18px; font-weight:700;'>{_('📍 Chọn địa điểm:', '📍 Select location:')}</label>",
    unsafe_allow_html=True
)
selected_city_display = st.selectbox(" ", location_display_names, key="selected_city", label_visibility="collapsed")
selected_city = next(k for k, v in location_names.items() if v == selected_city_display)
latitude, longitude = locations[selected_city]

crops = {
    "Ngô": (75, 100),
    "Chuối": (270, 365),
    "Ớt": (70, 90),
}
crop_names = {"Ngô": _("Ngô", "Corn"), "Chuối": _("Chuối", "Banana"), "Ớt": _("Ớt", "Chili pepper")}

# -----------------------
# Crop management with areas (updated)
# -----------------------
st.header(_("🌱 Quản lý cây trồng", "🌱 Crop Management"))

# helper stage function
def giai_doan_cay(crop, days):
    if crop == "Chuối":
        if days <= 14: return _("🌱 Mới trồng", "🌱 Newly planted")
        elif days <= 180: return _("🌿 Phát triển", "🌿 Growing")
        elif days <= 330: return _("🌼 Ra hoa", "🌼 Flowering")
        else: return _("🍌 Đã thu hoạch", "🍌 Harvested")
    elif crop == "Ngô":
        if days <= 25: return _("🌱 Mới trồng", "🌱 Newly planted")
        elif days <= 70: return _("🌿 Thụ phấn", "🌿 Pollination")
        elif days <= 100: return _("🌼 Trái phát triển", "🌼 Kernel growth")
        else: return _("🌽 Đã thu hoạch", "🌽 Harvested")
    elif crop == "Ớt":
        if days <= 20: return _("🌱 Mới trồng", "🌱 Newly planted")
        elif days <= 500: return _("🌼 Ra hoa", "🌼 Flowering")
        else: return _("🌶️ Đã thu hoạch", "🌶️ Harvested")

# ensure structure
if selected_city not in crop_data or not isinstance(crop_data[selected_city], dict):
    crop_data[selected_city] = {}
if "areas" not in crop_data[selected_city] or not isinstance(crop_data[selected_city]["areas"], dict):
    crop_data[selected_city]["areas"] = {}

areas = crop_data[selected_city]["areas"]

if user_type == _("Người điều khiển", "Control Administrator"):
    st.subheader(_("🌿 Quản lý khu vực trồng cây", "🌿 Manage Planting Areas"))

    area_list = list(areas.keys())
    area_list.append(_("➕ Thêm khu vực mới", "➕ Add new area"))
    st.markdown(
        f"<label style='font-size:18px; font-weight:700;'>{_('Chọn khu vực trồng', 'Select planting area')}</label>",
        unsafe_allow_html=True
    )
    selected_area = st.selectbox(" ", area_list, key="selected_area", label_visibility="collapsed")

    if selected_area == _("➕ Thêm khu vực mới", "➕ Add new area"):
        new_area_name = st.text_input(_("Nhập tên khu vực mới", "Enter new area name"))
        if new_area_name:
            if new_area_name not in areas:
                areas[new_area_name] = []
                crop_data[selected_city]["areas"] = areas
                save_json(DATA_FILE, crop_data)
                st.success(_("Đã tạo khu vực mới.", "New area created."))
                selected_area = new_area_name
            else:
                st.warning(_("Khu vực đã tồn tại.", "Area already exists."))

    # thêm cây vào khu vực
    if selected_area in areas:
        st.subheader(_("Thêm cây vào khu vực", "Add crop to area"))
        add_crop_display = st.selectbox(_("Chọn loại cây để thêm", "Select crop to add"), [crop_names[k] for k in crops.keys()])
        add_crop_key = next(k for k, v in crop_names.items() if v == add_crop_display)
        st.markdown(
            f"<label style='font-size:20px; font-weight:700;'>{_('Ngày gieo trồng', 'Planting date for this crop')}</label>",
            unsafe_allow_html=True
        )
        add_planting_date = st.date_input(" ", value=date.today(), key=f"planting_date_{add_crop_key}", label_visibility="collapsed")

        if st.button(_("➕ Thêm cây", "➕ Add crop")):
            crop_entry = {"crop": add_crop_key, "planting_date": add_planting_date.isoformat()}
            areas[selected_area].append(crop_entry)
            crop_data[selected_city]["areas"] = areas
            save_json(DATA_FILE, crop_data)
            st.success(_("Đã thêm cây vào khu vực.", "Crop added to area."))

    # hiển thị cây trong selected_area
    if selected_area in areas and areas[selected_area]:
        st.subheader(_("Thông tin cây trồng trong khu vực", "Plantings in area"))
        rows = []
        for p in areas[selected_area]:
            crop_k = p["crop"]
            pd_iso = p["planting_date"]
            try:
                pd_date = date.fromisoformat(pd_iso)
            except:
                pd_date = date.today()
            min_d, max_d = crops[crop_k]
            harvest_min = pd_date + timedelta(days=min_d)
            harvest_max = pd_date + timedelta(days=max_d)
            days_planted = (date.today() - pd_date).days
            rows.append({
                "crop": crop_names[crop_k],
                "planting_date": pd_date.strftime("%d/%m/%Y"),
                "expected_harvest_from": harvest_min.strftime("%d/%m/%Y"),
                "expected_harvest_to": harvest_max.strftime("%d/%m/%Y"),
                "days_planted": days_planted,
                "stage": giai_doan_cay(crop_k, days_planted)
            })
        df_plots = pd.DataFrame(rows)
        st.dataframe(df_plots)
    else:
        st.info(_("Khu vực này chưa có cây trồng.", "No crops planted in this area yet."))

    # ---- Phần cấu hình ngưỡng độ ẩm cho từng loại cây (chỉ controller) ----
    moisture_thresholds = config.get("moisture_thresholds", {"Ngô":65, "Chuối":70, "Ớt":65})
    st.markdown(
        f"<label style='font-size:18px; font-weight:700;'>{_('Đặt ngưỡng độ ẩm cho các loại cây (0-100%)', 'Set moisture thresholds for crops (0-100%)')}</label>",
        unsafe_allow_html=True
    )
    cols = st.columns(len(moisture_thresholds))
    i = 0
    for crop_k, val in moisture_thresholds.items():
        with cols[i]:
            new_val = st.slider(f"{crop_names.get(crop_k,crop_k)} ", min_value=0, max_value=100, value=val, key=f"thr_{crop_k}")
            moisture_thresholds[crop_k] = new_val
        i += 1

elif user_type == _("Người giám sát", " Monitoring Officer"):
    st.subheader(_("🌿 Xem thông tin cây trồng theo khu vực", "View plantings by area"))
    if areas:
        selected_area = st.selectbox(_("Chọn khu vực để xem", "Select area to view"), list(areas.keys()))
        if selected_area in areas and areas[selected_area]:
            rows = []
            for p in areas[selected_area]:
                crop_k = p["crop"]
                pd_iso = p["planting_date"]
                try:
                    pd_date = date.fromisoformat(pd_iso)
                except:
                    pd_date = date.today()
                min_d, max_d = crops[crop_k]
                harvest_min = pd_date + timedelta(days=min_d)
                harvest_max = pd_date + timedelta(days=max_d)
                days_planted = (date.today() - pd_date).days
                rows.append({
                    "crop": crop_names[crop_k],
                    "planting_date": pd_date.strftime("%d/%m/%Y"),
                    "expected_harvest_from": harvest_min.strftime("%d/%m/%Y"),
                    "expected_harvest_to": harvest_max.strftime("%d/%m/%Y"),
                    "days_planted": days_planted,
                    "stage": giai_doan_cay(crop_k, days_planted)
                })
            df_plots = pd.DataFrame(rows)
            st.dataframe(df_plots)
        else:
            st.info(_("Khu vực này chưa có cây trồng.", "No crops planted in this area yet."))
    else:
        st.info(_("Chưa có khu vực trồng nào.", "No planting areas available."))

# -----------------------
# Mode and Watering Schedule (shared config.json)
# -----------------------
st.header(_("⚙️ Cấu hình chung hệ thống", "⚙️ System General Configuration"))

if user_type == _("Người điều khiển", "Control Administrator"):
    col1, col2 = st.columns(2)

    with col1:
        st.markdown(_("### ⏲️ Khung giờ tưới nước", "### ⏲️ Watering time window"))

        # Lấy dữ liệu cũ hoặc mặc định
        default_slots = config.get("watering_slots", [{"start":"06:00","end":"08:00"}])
        num_slots = st.number_input(_("Số khung giờ", "Number of slots"), min_value=1, max_value=5, value=len(default_slots))

        watering_slots = []
        for i in range(num_slots):
            slot = default_slots[i] if i < len(default_slots) else {"start": "06:00", "end": "06:30"}
            c1, c2 = st.columns(2)
            start_t = c1.time_input(_("Bắt đầu", "Start"), value=datetime.strptime(slot["start"], "%H:%M").time(), key=f"start_{i}")
            end_t = c2.time_input(_("Kết thúc", "End"), value=datetime.strptime(slot["end"], "%H:%M").time(), key=f"end_{i}")
            watering_slots.append({"start": start_t.strftime("%H:%M"), "end": end_t.strftime("%H:%M")})

    with col2:
        st.markdown(_("### 🔄 Chế độ hoạt động", "### 🔄 Operation mode"))
        st.markdown(
            f"<label style='font-size:18px; font-weight:700;'>{_('Chọn chế độ', 'Select mode')}</label>",
            unsafe_allow_html=True
        )
        mode_sel = st.radio(" ", [_("Auto", "Auto"), _("Manual", "Manual")], index=0 if config.get("mode","auto")=="auto" else 1, key="mode_sel", label_visibility="collapsed")

    # Nút lưu cấu hình chung (gửi config đến ESP32 thay vì lệnh bật/tắt)
    if st.button(_("💾 Lưu cấu hình và gửi tới ESP32", "💾 Save configuration and send to ESP32")):
        config["watering_slots"] = watering_slots
        config["mode"] = "auto" if mode_sel == _("Auto", "Auto") else "manual"
        config["moisture_thresholds"] = moisture_thresholds
        save_json(CONFIG_FILE, config)

        ok = send_config_to_esp32(config)
        if ok:
            st.success(_("Đã lưu cấu hình và gửi tới ESP32.", "Configuration saved and sent to ESP32."))
        else:
            st.warning(_("Cấu hình đã lưu cục bộ nhưng gửi tới ESP32 thất bại.", "Configuration saved locally but failed to send to ESP32."))

else:
    # display current config (read-only)
    ws = config.get("watering_slots", [{"start":"06:00","end":"08:00"}])
    ws_str = ", ".join([f"{s['start']}-{s['end']}" for s in ws])
    st.markdown(_("⏲️ Khung giờ tưới nước hiện tại:", "⏲️ Current watering time window:") + f" **{ws_str}**")
    st.markdown(_("🔄 Chế độ hoạt động hiện tại:", "🔄 Current operation mode:") + f" **{config.get('mode','auto').capitalize()}**")

mode_flag = config.get("mode", "auto")

# -----------------------
# Weather API (unchanged)
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
col1.markdown(big_label("🌡️ Nhiệt độ", "🌡️ Temperature"), unsafe_allow_html=True)
col1.metric("", f"{current_weather.get('temperature_2m', 'N/A')} °C")

col2.markdown(big_label("💧 Độ ẩm", "💧 Humidity"), unsafe_allow_html=True)
col2.metric("", f"{current_weather.get('relative_humidity_2m', 'N/A')} %")

col3.markdown(big_label("☔ Khả năng mưa", "☔ Precipitation Probability"), unsafe_allow_html=True)
col3.metric("", f"{current_weather.get('precipitation_probability', 'N/A')} %")

# -----------------------
# Sensor data from ESP32
# -----------------------
st.subheader(_("📡 Dữ liệu cảm biến thực tế (ESP32)", "📡 Real sensor data (ESP32)"))

pump_status = "UNKNOWN"

if sensor_data:
    soil_moisture = sensor_data.get("soil_moisture")
    soil_temp = sensor_data.get("soil_temp")
    light_level = sensor_data.get("light")
    water_flow = sensor_data.get("water_flow")
    pump_status = sensor_data.get("pump_status", "OFF")

    st.write(f"- {_('Độ ẩm đất hiện tại', 'Current soil moisture')}: {soil_moisture} %")
    st.write(f"- {_('Nhiệt độ đất', 'Soil temperature')}: {soil_temp} °C")
    st.write(f"- {_('Cường độ ánh sáng', 'Light intensity')}: {light_level} lux")
    st.write(f"- {_('Lưu lượng nước', 'Water flow')}: {water_flow} L/min")

    # LED pump status
    led_color = "#00FF00" if str(pump_status).upper() == "ON" else "#555555"
    st.markdown(f"<div style='display:flex; align-items:center;'><div class='led' style='background-color:{led_color};'></div><strong>{_('Trạng thái bơm', 'Pump status')}: {pump_status}</strong></div>", unsafe_allow_html=True)

    # Lưu dữ liệu mới vào lịch sử
    if soil_moisture is not None and soil_temp is not None:
        add_history_record(soil_moisture, soil_temp)
    if water_flow is not None:
        add_flow_record(water_flow)
else:
    st.info(_("Chưa có dữ liệu cảm biến thực tế từ ESP32.", "No real sensor data from ESP32 yet."))
    soil_moisture = None

# -----------------------
# Irrigation decision (web no longer sends ON/OFF)
# -----------------------
st.header(_("🚰 Điều khiển tưới nước (Web chỉ gửi cấu hình - ESP32 tự xử lý)", "🚰 Irrigation Control (Web only sends config - ESP32 handles pump)") )

# For backward display compatibility show current effective watering schedule string
ws = config.get("watering_slots", [{"start":"06:00","end":"08:00"}])
ws_str = ", ".join([f"{s['start']}-{s['end']}" for s in ws])
st.write(f"- {_('Khung giờ tưới nước (đã gửi)', 'Watering schedule (sent)')}: {ws_str}")
st.write(f"- {_('Chế độ (đã gửi)', 'Mode (sent)')}: {config.get('mode','auto')}")
st.write(f"- {_('Ngưỡng độ ẩm (đã gửi)', 'Moisture thresholds (sent)')}: {config.get('moisture_thresholds', {})}")
st.write(f"- {_('Thời gian hiện tại', 'Current time')}: {datetime.now(vn_tz).strftime('%H:%M:%S')}")
st.write(f"- {_('Dữ liệu độ ẩm hiện tại', 'Current soil moisture')}: {soil_moisture if soil_moisture is not None else 'N/A'} %")

if config.get('mode','auto') == 'manual':
    st.info(_("🔧 Chế độ thủ công - ESP32 sẽ chờ cấu hình 'manual' và người điều khiển có thể thay đổi ngưỡng/khung giờ từ web.", "🔧 Manual mode - ESP32 will use mode 'manual' and controller may update thresholds/schedule from web."))

# -----------------------
# Show historical charts (độ ẩm và lưu lượng)
# -----------------------
st.header(_("📊 Biểu đồ lịch sử độ ẩm, nhiệt độ, lưu lượng nước", "📊 Historical Charts"))

st.markdown(
    f"<label style='font-size:18px; font-weight:700;'>{_('Chọn ngày để xem dữ liệu', 'Select date for chart')}</label>",
    unsafe_allow_html=True
)
chart_date = st.date_input(" ", value=date.today(), key="chart_date", label_visibility="collapsed")

history_data = load_json(HISTORY_FILE, []) or []
flow_data = load_json(FLOW_FILE, []) or []

if len(history_data) == 0 or len(flow_data) == 0:
    st.info(_("📋 Chưa có dữ liệu lịch sử để hiển thị.", "📋 No historical data to display."))
else:
    df_hist_all = pd.DataFrame(history_data)
    if 'timestamp' in df_hist_all.columns:
        df_hist_all['timestamp'] = pd.to_datetime(df_hist_all['timestamp'], errors='coerce')
        df_hist_all = df_hist_all.dropna(subset=['timestamp'])
        df_hist_all['date'] = df_hist_all['timestamp'].dt.date
        df_day = df_hist_all[df_hist_all['date'] == chart_date]
    else:
        df_day = pd.DataFrame()

    df_flow_all = pd.DataFrame(flow_data)
    if 'time' in df_flow_all.columns:
        df_flow_all['time'] = pd.to_datetime(df_flow_all['time'], errors='coerce')
        df_flow_all = df_flow_all.dropna(subset=['time'])
        df_flow_all['date'] = df_flow_all['time'].dt.date
        df_flow_day = df_flow_all[df_flow_all['date'] == chart_date]
    else:
        df_flow_day = pd.DataFrame()
    if df_day.empty or df_flow_day.empty:
        st.info(_("📋 Không có dữ liệu trong ngày này.", "📋 No data for selected date."))
    else:
        import matplotlib.pyplot as plt
        fig, ax1 = plt.subplots(figsize=(12, 5))
        ax1.plot(pd.to_datetime(df_day['timestamp']), df_day['sensor_hum'], label=_("Độ ẩm đất", "Soil Humidity"))
        ax1.set_xlabel(_("Thời gian", "Time"))
        ax1.set_ylabel(_("Độ ẩm đất (%)", "Soil Humidity (%)"))
        ax2 = ax1.twinx()
        ax2.plot(pd.to_datetime(df_day['timestamp']), df_day['sensor_temp'], label=_("Nhiệt độ", "Temperature"))
        ax2.set_ylabel(_("Nhiệt độ (°C)", "Temperature (°C)"))
        ax1.legend(loc='upper left')
        ax2.legend(loc='upper right')
        plt.title(_("Lịch sử độ ẩm đất và nhiệt độ", "Soil Humidity and Temperature History"))
        plt.xticks(rotation=45)
        plt.tight_layout()
        st.pyplot(fig)

        fig2, ax3 = plt.subplots(figsize=(12, 3))
        ax3.plot(pd.to_datetime(df_flow_day['time']), df_flow_day['flow'], label=_("Lưu lượng nước (L/min)", "Water Flow (L/min)"))
        ax3.set_xlabel(_("Thời gian", "Time"))
        ax3.set_ylabel(_("Lưu lượng nước (L/min)", "Water Flow (L/min)"))
        ax3.legend()
        plt.title(_("Lịch sử lưu lượng nước", "Water Flow History"))
        plt.xticks(rotation=45)
        plt.tight_layout()
        st.pyplot(fig2)

# -----------------------
# Lịch sử tưới
# -----------------------
st.header(_("📅 Lịch sử tưới nước", "📅 Irrigation History"))

history = load_json(HISTORY_FILE, [])
if history:
    df_hist = pd.DataFrame(history)
    if 'timestamp' in df_hist.columns:
        df_hist["timestamp"] = pd.to_datetime(df_hist["timestamp"], errors='coerce')
    df_hist = df_hist.sort_values(by="timestamp", ascending=False)
    st.dataframe(df_hist)
else:
    st.info(_("Chưa có lịch sử tưới.", "No irrigation history."))

# -----------------------
# Footer
# -----------------------
st.markdown("---")
st.caption("📡 API thời tiết: Open-Meteo | Dữ liệu cảm biến: ESP32-WROOM (MQTT)")
st.caption("Người thực hiện: Ngô Nguyễn Định Tường-Mai Phúc Khang")
