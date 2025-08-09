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
import threading
import paho.mqtt.client as mqtt
import matplotlib.pyplot as plt

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
selected_city_display = st.selectbox(_("📍 Chọn địa điểm:", "📍 Select location:"), location_display_names)
selected_city = next(k for k, v in location_names.items() if v == selected_city_display)
latitude, longitude = locations[selected_city]

crops = {
    "Ngô": (75, 100),
    "Chuối": (270, 365),
    "Ớt": (70, 90),
}
required_soil_moisture = {"Ngô": 65, "Chuối": 70, "Ớt": 65}
crop_names = {"Ngô": _("Ngô", "Corn"), "Chuối": _("Chuối", "Banana"), "Ớt": _("Ớt", "Chili pepper")}

# -----------------------
# Crop management (unchanged)
# -----------------------
st.header(_("🌱 Quản lý cây trồng", "🌱 Crop Management"))

mode_flag = config.get("mode", "auto")

if user_type == _("Người điều khiển", "Control Administrator"):
    st.subheader(_("Thêm / Cập nhật vùng trồng", "Add / Update Plantings"))
    multiple = st.checkbox(_("Trồng nhiều loại trên khu vực này", "Plant multiple crops in this location"), value=False)
    if selected_city not in crop_data:
        crop_data[selected_city] = {"plots": [], "mode": mode_flag}
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
            crop_data[selected_city] = {"plots": [{"crop": selected_crop, "planting_date": planting_date.isoformat()}], "mode": mode_flag}
            save_json(DATA_FILE, crop_data)
            st.success(_("Đã lưu thông tin trồng.", "Planting info saved."))

if user_type == _("Người giám sát", " Monitoring Officer"):
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
# Hiển thị dữ liệu cảm biến thực tế từ ESP32 (không mô phỏng)
# -----------------------
st.subheader(_("📡 Dữ liệu cảm biến thực tế từ ESP32", "📡 Real Sensor Data from ESP32"))

if len(history_data) == 0 or len(flow_data) == 0:
    st.info(_("⚠️ Chưa nhận được dữ liệu cảm biến từ ESP32.", "⚠️ No sensor data received from ESP32 yet."))
else:
    latest_record = history_data[-1]
    st.write(f"{_('Độ ẩm đất', 'Soil Moisture')}: {latest_record.get('sensor_hum', 'N/A')}%")
    st.write(f"{_('Nhiệt độ đất', 'Soil Temperature')}: {latest_record.get('sensor_temp', 'N/A')} °C")

# -----------------------
# Quyết định tưới dựa trên dữ liệu thực tế
# -----------------------
current_time = datetime.now(vn_tz).time()
start_time = datetime.strptime(config["watering_schedule"].split("-")[0], "%H:%M").time()
end_time = datetime.strptime(config["watering_schedule"].split("-")[1], "%H:%M").time()
is_in_watering_time = start_time <= current_time <= end_time

if len(history_data) > 0:
    current_soil_moisture = history_data[-1].get("sensor_hum", None)
else:
    current_soil_moisture = None

should_water = False

if mode_flag == "auto":
    if current_soil_moisture is not None:
        should_water = current_soil_moisture < 65 and is_in_watering_time
    else:
        st.warning(_("⚠️ Chưa có dữ liệu độ ẩm đất để quyết định tưới.", "⚠️ No soil moisture data to make irrigation decision."))

elif mode_flag == "manual":
    if manual_control_type == _("Thủ công trên app", "Manual on app") or manual_control_type == "Manual on app":
        st.warning(_("⚠️ Đang ở chế độ thủ công trên app. Bạn có thể bật hoặc tắt bơm thủ công.", "⚠️ Manual control on app. You can turn pump ON or OFF manually."))

        col_on, col_off = st.columns(2)
        with col_on:
            if st.button(_("Bật bơm thủ công", "Turn ON pump manually")):
                # TODO: Gửi lệnh bật bơm qua MQTT hoặc HTTP
                st.success(_("Đã gửi lệnh bật bơm", "Sent command to turn ON pump"))
        with col_off:
            if st.button(_("Tắt bơm thủ công", "Turn OFF pump manually")):
                # TODO: Gửi lệnh tắt bơm qua MQTT hoặc HTTP
                st.success(_("Đã gửi lệnh tắt bơm", "Sent command to turn OFF pump"))

        should_water = False
    else:
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
# Biểu đồ lịch sử độ ẩm, nhiệt độ, lưu lượng nước
# -----------------------
st.header(_("📊 Biểu đồ lịch sử độ ẩm, nhiệt độ, lưu lượng nước", "📊 Historical Charts"))

chart_date = st.date_input(_("Chọn ngày để xem dữ liệu", "Select date for chart"), value=date.today())

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
        # Biểu đồ độ ẩm đất và nhiệt độ
        fig, ax1 = plt.subplots(figsize=(12, 5))
        ax1.plot(pd.to_datetime(df_day['timestamp']), df_day['sensor_hum'], 'b-', label=_("Độ ẩm đất", "Soil Humidity"))
        ax1.set_xlabel(_("Thời gian", "Time"))
        ax1.set_ylabel(_("Độ ẩm đất (%)", "Soil Humidity (%)"), color='b')
        ax1.tick_params(axis='y', labelcolor='b')

        ax2 = ax1.twinx()
        ax2.plot(pd.to_datetime(df_day['timestamp']), df_day['sensor_temp'], 'r-', label=_("Nhiệt độ", "Temperature"))
        ax2.set_ylabel(_("Nhiệt độ (°C)", "Temperature (°C)"), color='r')
        ax2.tick_params(axis='y', labelcolor='r')

        ax1.legend(loc='upper left')
        ax2.legend(loc='upper right')
        plt.title(_("Lịch sử độ ẩm đất và nhiệt độ", "Soil Humidity and Temperature History"))
        plt.xticks(rotation=45)
        plt.tight_layout()
        st.pyplot(fig)

        # Biểu đồ lưu lượng nước
        fig2, ax3 = plt.subplots(figsize=(12, 3))
        ax3.plot(pd.to_datetime(df_flow_day['time']), df_flow_day['flow'], 'g-', label=_("Lưu lượng nước (L/min)", "Water Flow (L/min)"))
        ax3.set_xlabel(_("Thời gian", "Time"))
        ax3.set_ylabel(_("Lưu lượng nước (L/min)", "Water Flow (L/min)"), color='g')
        ax3.tick_params(axis='y', labelcolor='g')
        ax3.legend()
        plt.title(_("Lịch sử lưu lượng nước", "Water Flow History"))
        plt.xticks(rotation=45)
        plt.tight_layout()
        st.pyplot(fig2)

# -----------------------
# MQTT Client để nhận dữ liệu ESP32 (nền)
# -----------------------
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_TOPIC_SENSOR = "esp32/sensor"
MQTT_TOPIC_FLOW = "esp32/flow"

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        client.subscribe(MQTT_TOPIC_SENSOR)
        client.subscribe(MQTT_TOPIC_FLOW)
    else:
        print("MQTT Connection failed, rc=", rc)

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        if msg.topic == MQTT_TOPIC_SENSOR:
            hum = payload.get("soil_moisture")
            temp = payload.get("soil_temperature")
            if hum is not None and temp is not None:
                add_history_record(hum, temp)
        elif msg.topic == MQTT_TOPIC_FLOW:
            flow = payload.get("flow")
            if flow is not None:
                add_flow_record(flow)
    except Exception as e:
        print("MQTT message error:", e)

client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message

def mqtt_loop():
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_forever()

# Chạy MQTT thread nền
threading.Thread(target=mqtt_loop, daemon=True).start()
