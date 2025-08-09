# web_esp.py
import streamlit as st
from datetime import datetime, timedelta, date, time
import random
from PIL import Image
import json
import os
from streamlit_autorefresh import st_autorefresh
import pytz
import pandas as pd
import threading
import paho.mqtt.client as mqtt

# --- Cấu hình ---
st.set_page_config(page_title="Smart Irrigation WebApp", layout="wide")
st_autorefresh(interval=60 * 1000, key="refresh")

# I18N
lang = st.sidebar.selectbox("🌐 Language / Ngôn ngữ", ["Tiếng Việt", "English"])
vi = lang == "Tiếng Việt"
def _(vi_text, en_text):
    return vi_text if vi else en_text

# File lưu dữ liệu
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

vn_tz = pytz.timezone("Asia/Ho_Chi_Minh")
now = datetime.now(vn_tz)

# Load dữ liệu
crop_data = load_json(DATA_FILE, {})
history_data = load_json(HISTORY_FILE, [])
flow_data = load_json(FLOW_FILE, [])
config = load_json(CONFIG_FILE, {"watering_schedule": "06:00-08:00", "mode": "auto"})

# Header và logo
try:
    st.markdown("""
    <style>
    .block-container { padding-top: 1rem; }
    h3 { color: #000000 !important; font-size: 20px !important; font-family: Arial, sans-serif !important; font-weight: bold !important; }
    </style>
    """, unsafe_allow_html=True)
    st.image("logo1.png", width=1200)
except:
    st.warning(_("❌ Không tìm thấy logo1.png", "❌ logo1.png not found"))

st.markdown(f"<h2 style='text-align: center; font-size: 50px;'>🌾 {_('Hệ thống tưới tiêu nông nghiệp thông minh', 'Smart Agricultural Irrigation System')} 🌾</h2>", unsafe_allow_html=True)
st.markdown(f"<h3>⏰ {_('Thời gian hiện tại', 'Current time')}: {now.strftime('%d/%m/%Y')}</h3>", unsafe_allow_html=True)

# Sidebar - vai trò và xác thực
st.sidebar.title(_("🔐 Chọn vai trò người dùng", "🔐 Select User Role"))
user_type = st.sidebar.radio(_("Bạn là:", "You are:"), [_("Người điều khiển", "Control Administrator"), _("Người giám sát", "Monitoring Officer")])

if user_type == _("Người điều khiển", "Control Administrator"):
    password = st.sidebar.text_input(_("🔑 Nhập mật khẩu:", "🔑 Enter password:"), type="password")
    if password != "admin123":
        st.sidebar.error(_("❌ Mật khẩu sai. Truy cập bị từ chối.", "❌ Incorrect password. Access denied."))
        st.stop()
    else:
        st.sidebar.success(_("✅ Xác thực thành công.", "✅ Authentication successful."))

# Địa điểm và cây trồng
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

crops = {
    "Ngô": (75, 100),
    "Chuối": (270, 365),
    "Ớt": (70, 90),
}
crop_names = {"Ngô": _("Ngô", "Corn"), "Chuối": _("Chuối", "Banana"), "Ớt": _("Ớt", "Chili pepper")}

# Quản lý cây trồng
st.header(_("🌱 Quản lý cây trồng", "🌱 Crop Management"))

if user_type == _("Người điều khiển", "Control Administrator"):
    st.subheader(_("Thêm / Cập nhật vùng trồng", "Add / Update Plantings"))
    multiple = st.checkbox(_("Trồng nhiều loại trên khu vực này", "Plant multiple crops in this location"), value=False)
    if selected_city not in crop_data:
        crop_data[selected_city] = {"plots": []}

    if multiple:
        st.markdown(_("Thêm từng loại cây vào khu vực (bấm 'Thêm cây')", "Add each crop to the area (click 'Add crop')"))
        col1, col2 = st.columns([2, 1])
        with col1:
            add_crop = st.selectbox(_("Chọn loại cây để thêm", "Select crop to add"), [crop_names[k] for k in crops.keys()])
            add_crop_key = next(k for k, v in crop_names.items() if v == add_crop)
            add_planting_date = st.date_input(_("Ngày gieo trồng", "Planting date for this crop"), value=date.today())
        with col2:
            if st.button(_("➕ Thêm cây", "➕ Add crop")):
                crop_entry = {"crop": add_crop_key, "planting_date": add_planting_date.isoformat()}
                crop_data[selected_city]["plots"].append(crop_entry)
                save_json(DATA_FILE, crop_data)
                st.success(_("Đã thêm cây vào khu vực.", "Crop added to location."))
    else:
        crop_display_names = [crop_names[k] for k in crops.keys()]
        selected_crop_display = st.selectbox(_("🌱 Chọn loại nông sản:", "🌱 Select crop type:"), crop_display_names)
        selected_crop = next(k for k, v in crop_names.items() if v == selected_crop_display)
        planting_date = st.date_input(_("📅 Ngày gieo trồng:", "📅 Planting date:"), value=date.today())
        if st.button(_("💾 Lưu thông tin trồng", "💾 Save planting info")):
            crop_data[selected_city] = {"plots": [{"crop": selected_crop, "planting_date": planting_date.isoformat()}]}
            save_json(DATA_FILE, crop_data)
            st.success(_("Đã lưu thông tin trồng.", "Planting info saved."))

if user_type == _("Người giám sát", "Monitoring Officer"):
    st.subheader(_("Thông tin cây trồng tại khu vực", "Plantings at this location"))
    if selected_city in crop_data and crop_data[selected_city].get("plots"):
        plots = crop_data[selected_city]["plots"]
        rows = []
        for p in plots:
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
        st.info(_("📍 Chưa có thông tin gieo trồng tại khu vực này.", "📍 No crop information available in this location."))

# Cấu hình chung hệ thống
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

def is_in_watering_time():
    now_time = datetime.now(vn_tz).time()
    start = datetime.strptime(config["watering_schedule"].split("-")[0], "%H:%M").time()
    end = datetime.strptime(config["watering_schedule"].split("-")[1], "%H:%M").time()
    if start <= end:
        return start <= now_time <= end
    else:
        return now_time >= start or now_time <= end

in_watering_time = is_in_watering_time()

# MQTT setup
MQTT_BROKER = "test.mosquitto.org"
MQTT_PORT = 1883
TOPIC_DATA = "esp32/sensor/data"
TOPIC_COMMAND = "smart_irrigation/command"

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("MQTT connected successfully")
        client.subscribe(TOPIC_DATA)
    else:
        print(f"MQTT failed to connect, return code {rc}")

def on_message(client, userdata, msg):
    try:
        payload_str = msg.payload.decode()
        data = json.loads(payload_str)
        st.session_state.sensor_data = data
        st.session_state.last_data_time = datetime.now(vn_tz)
        st.session_state.esp32_connected = True
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

if "mqtt_thread_started" not in st.session_state:
    st.session_state.mqtt_thread_started = True
    st.session_state.sensor_data = None
    st.session_state.last_data_time = None
    st.session_state.esp32_connected = False
    threading.Thread(target=mqtt_thread, daemon=True).start()

# Kiểm tra trạng thái kết nối
if st.session_state.last_data_time is None or (datetime.now(vn_tz) - st.session_state.last_data_time).total_seconds() > 5:
    st.session_state.esp32_connected = False
    st.warning(_("⚠️ Không kết nối được với ESP32. Vui lòng kiểm tra thiết bị.", "⚠️ Cannot connect to ESP32. Please check the device."))

if st.session_state.esp32_connected:
    st.success(_("✅ Đã kết nối thành công với ESP32.", "✅ Successfully connected to ESP32."))
    sensor = st.session_state.sensor_data or {}
    soil_moisture = sensor.get("soil_moisture", None)
    light = sensor.get("light", None)
    water_flow = sensor.get("water_flow", None)

    st.write(f"{_('Độ ẩm đất', 'Soil Moisture')}: {soil_moisture}%")
    st.write(f"{_('Ánh sáng', 'Light')}: {light} lux")
    st.write(f"{_('Lưu lượng nước', 'Water Flow')}: {water_flow} L/min")
else:
    st.info(_("⏳ Đang chờ dữ liệu từ ESP32...", "⏳ Waiting for data from ESP32..."))

# Logic tưới tự động (đơn giản)
if st.session_state.esp32_connected:
    if config.get("mode", "auto") == "auto" and in_watering_time:
        threshold = 65
        if soil_moisture is not None:
            if soil_moisture < threshold:
                st.warning(_("💧 Độ ẩm đất thấp. Cần tưới nước!", "💧 Soil moisture low. Need to irrigate!"))
                # TODO: Thêm xác nhận bật bơm, gửi lệnh MQTT
            else:
                st.info(_("🌿 Độ ẩm đất đủ, không cần tưới.", "🌿 Soil moisture sufficient, no need to irrigate."))
        else:
            st.error(_("❌ Dữ liệu độ ẩm đất không hợp lệ.", "❌ Invalid soil moisture data."))

# Lịch sử tưới tiêu
st.header(_("📊 Lịch sử tưới tiêu", "📊 Irrigation History"))
history = load_json(HISTORY_FILE, [])
if history:
    df_hist = pd.DataFrame(history)
    st.dataframe(df_hist)
else:
    st.info(_("Chưa có dữ liệu lịch sử tưới tiêu.", "No irrigation history data."))

# Lưu lượng nước
st.header(_("💧 Dữ liệu lưu lượng nước", "💧 Water Flow Data"))
flow = load_json(FLOW_FILE, [])
if flow:
    df_flow = pd.DataFrame(flow)
    st.line_chart(df_flow.set_index("time")["flow"])
else:
    st.info(_("Chưa có dữ liệu lưu lượng nước.", "No water flow data."))
# -----------------------
# Footer
# -----------------------
st.markdown("---")
st.caption("📡 API thời tiết: Open-Meteo | Dữ liệu cảm biến: ESP32-WROOM (giả lập nếu chưa có)")
st.caption("Người thực hiện: Ngô Nguyễn Định Tường-Mai Phúc Khang")








