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
import matplotlib.pyplot as plt
import threading
import paho.mqtt.client as mqtt

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
# Locations & crops
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
# Crop management
# -----------------------
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
# Mode and Watering Schedule (simplified)
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

    if st.button(_("💾 Lưu cấu hình", "💾 Save configuration")):
        config["watering_schedule"] = f"{start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')}"
        if main_mode == _("Tự động", "Automatic"):
            config["mode"] = "auto"
        else:
            config["mode"] = "manual"
        save_json(CONFIG_FILE, config)
        st.success(_("Đã lưu cấu hình.", "Configuration saved."))

else:
    st.markdown(
        _("⏲️ Khung giờ tưới nước hiện tại:", "⏲️ Current watering time window:") + f" **{config['watering_schedule']}**"
    )
    mode_display = _("Tự động", "Automatic") if config.get("mode", "auto") == "auto" else _("Thủ công", "Manual")
    st.markdown(_("🔄 Chế độ hoạt động hiện tại:", "🔄 Current operation mode:") + f" **{mode_display}**")

# -----------------------
# Quyết định tưới dựa trên dữ liệu thực tế
# -----------------------
current_time = datetime.now(vn_tz).time()
start_time_cfg = datetime.strptime(config["watering_schedule"].split("-")[0], "%H:%M").time()
end_time_cfg = datetime.strptime(config["watering_schedule"].split("-")[1], "%H:%M").time()

# Xử lý khung giờ tưới có thể qua nửa đêm (ví dụ 22:00-06:00)
if start_time_cfg <= end_time_cfg:
    is_in_watering_time = start_time_cfg <= current_time <= end_time_cfg
else:
    is_in_watering_time = current_time >= start_time_cfg or current_time <= end_time_cfg

# Lấy độ ẩm tiêu chuẩn của cây trồng khu vực hiện tại (lấy cây đầu tiên trong plots)
if selected_city in crop_data and crop_data[selected_city].get("plots"):
    crop_key = crop_data[selected_city]["plots"][0]["crop"]
    soil_moisture_standard = required_soil_moisture.get(crop_key, 65)
else:
    soil_moisture_standard = 65  # mặc định

# Lấy dữ liệu độ ẩm đất, nhiệt độ từ history (ESP32 gửi lên)
if len(history_data) > 0:
    current_soil_moisture = history_data[-1].get("sensor_hum", None)
    current_soil_temp = history_data[-1].get("sensor_temp", None)
else:
    current_soil_moisture = None
    current_soil_temp = None

should_water = False

if config.get("mode", "auto") == "auto":
    if current_soil_moisture is not None:
        if current_soil_moisture < soil_moisture_standard * 0.8 and is_in_watering_time:
            should_water = True
        else:
            should_water = False
    else:
        st.warning(_("⚠️ Chưa có dữ liệu độ ẩm đất để quyết định tưới.", "⚠️ No soil moisture data to make irrigation decision."))

elif config.get("mode") == "manual":
    should_water = False  # Không tự bật bơm khi manual

# Hiển thị trạng thái bơm và quyết định tưới
st.subheader(_("🚰 Trạng thái bơm nước", "🚰 Pump Status"))

if config.get("mode") == "auto":
    if should_water:
        st.warning(_("⚠️ Tự động bật bơm vì độ ẩm đất thấp.", "⚠️ Automatically turning pump ON due to low soil moisture."))
        # TODO: Gửi lệnh bật bơm xuống ESP32 qua MQTT hoặc HTTP ở đây
    else:
        st.info(_("💧 Bơm tắt hoặc không cần bật.", "💧 Pump OFF or no need to turn on."))

elif config.get("mode") == "manual":
    # Ở chế độ manual, chỉ hiển thị trạng thái bơm (giả sử có biến global pump_status đọc từ cảm biến tủ điện hoặc ESP32)
    pump_status = False
    st.info(_("💧 Chế độ thủ công. Bơm đang tắt hoặc được bật thủ công ngoài tủ điện.", "💧 Manual mode. Pump is OFF or controlled manually outside cabinet."))

# -----------------------
# Hiển thị đồ thị dữ liệu độ ẩm, nhiệt độ đất thực tế từ ESP32 (history_data)
# -----------------------
st.header(_("📊 Dữ liệu cảm biến thực tế từ ESP32-WROOM", "📊 Real Sensor Data from ESP32-WROOM"))

if len(history_data) == 0:
    st.info(_("Chưa có dữ liệu cảm biến nào.", "No sensor data available yet."))
else:
    times = [datetime.fromisoformat(rec["timestamp"]).astimezone(vn_tz) for rec in history_data[-100:]]
    hums = [rec["sensor_hum"] for rec in history_data[-100:]]
    temps = [rec["sensor_temp"] for rec in history_data[-100:]]

    df = pd.DataFrame({"Time": times, "Soil Humidity (%)": hums, "Soil Temperature (°C)": temps})
    df = df.set_index("Time")

    st.line_chart(df)

# -----------------------
# MQTT Client để nhận dữ liệu từ ESP32 (background thread)
# -----------------------
mqtt_broker = "broker.hivemq.com"
mqtt_port = 1883
mqtt_topic_humidity = "esp32/soil_humidity"
mqtt_topic_temperature = "esp32/soil_temperature"

mqtt_client = mqtt.Client()

def on_connect(client, userdata, flags, rc):
    print("Connected to MQTT broker with result code "+str(rc))
    client.subscribe([(mqtt_topic_humidity, 0), (mqtt_topic_temperature, 0)])

sensor_data = {"soil_humidity": None, "soil_temperature": None}

def on_message(client, userdata, msg):
    topic = msg.topic
    payload = msg.payload.decode()
    try:
        val = float(payload)
    except:
        val = None

    if topic == mqtt_topic_humidity:
        sensor_data["soil_humidity"] = val
    elif topic == mqtt_topic_temperature:
        sensor_data["soil_temperature"] = val

    # Khi nhận đủ 2 dữ liệu, lưu vào lịch sử
    if sensor_data["soil_humidity"] is not None and sensor_data["soil_temperature"] is not None:
        add_history_record(sensor_data["soil_humidity"], sensor_data["soil_temperature"])
        # reset để tránh lưu trùng
        sensor_data["soil_humidity"] = None
        sensor_data["soil_temperature"] = None

def mqtt_loop():
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message
    mqtt_client.connect(mqtt_broker, mqtt_port, 60)
    mqtt_client.loop_forever()

# Chạy thread MQTT khi chưa chạy
if "mqtt_thread" not in st.session_state:
    t = threading.Thread(target=mqtt_loop, daemon=True)
    t.start()
    st.session_state["mqtt_thread"] = t

# -----------------------
# Thông báo và hướng dẫn
# -----------------------
st.markdown("---")
st.info(
    _(
        "🌟 Hệ thống sẽ tự động cập nhật dữ liệu độ ẩm và nhiệt độ đất từ cảm biến ESP32.\n"
        "🌟 Chế độ 'Tự động' sẽ tự bật bơm nếu độ ẩm thấp hơn tiêu chuẩn.\n"
        "🌟 Chế độ 'Thủ công' không tự bật bơm, chỉ hiển thị trạng thái.",
        "🌟 System automatically updates soil moisture and temperature data from ESP32 sensors.\n"
        "🌟 'Automatic' mode turns pump ON if moisture is below threshold.\n"
        "🌟 'Manual' mode does not auto control pump, only displays status."
    )
)

