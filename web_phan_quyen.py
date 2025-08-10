# web_esp.py
# Streamlit app for Smart Irrigation:
# - receives real sensor data via MQTT or HTTP POST (Flask)
# - stores history to JSON files
# - shows charts (soil moisture, soil temp, water flow) selectable by date
# - Auto / Manual modes (auto will send pump ON/OFF via MQTT when needed)
# - No simulated sensor data included

import streamlit as st
from datetime import datetime, date, time, timedelta
from PIL import Image
import json
import os
import threading
import pytz
import pandas as pd
import matplotlib.pyplot as plt
from flask import Flask, request, jsonify
import paho.mqtt.client as mqtt

# -----------------------
# Config & files
# -----------------------
st.set_page_config(page_title="Smart Irrigation WebApp", layout="wide")
try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=60 * 1000, key="refresh")
except:
    pass  # optional auto refresh

DATA_FILE = "crop_data.json"
HISTORY_FILE = "history_irrigation.json"  # sensor history: timestamp, sensor_hum, sensor_temp
FLOW_FILE = "flow_data.json"               # flow history: time, flow
CONFIG_FILE = "config.json"

vn_tz = pytz.timezone("Asia/Ho_Chi_Minh")

# -----------------------
# Utility: load/save JSON
# -----------------------
def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# -----------------------
# Add history helpers (use VN timezone)
# -----------------------
def add_history_record(sensor_hum, sensor_temp):
    now_iso = datetime.now(vn_tz).isoformat()
    history = load_json(HISTORY_FILE, [])
    history.append({"timestamp": now_iso, "sensor_hum": sensor_hum, "sensor_temp": sensor_temp})
    save_json(HISTORY_FILE, history)

def add_flow_record(flow_val):
    now_iso = datetime.now(vn_tz).isoformat()
    flow = load_json(FLOW_FILE, [])
    flow.append({"time": now_iso, "flow": flow_val})
    save_json(FLOW_FILE, flow)

# -----------------------
# Load persisted config / data
# -----------------------
crop_data = load_json(DATA_FILE, {})
history_data = load_json(HISTORY_FILE, [])
flow_data = load_json(FLOW_FILE, [])
config = load_json(CONFIG_FILE, {"watering_schedule": "06:00-08:00", "mode": "auto"})

# -----------------------
# I18N simple
# -----------------------
lang = st.sidebar.selectbox("🌐 Language / Ngôn ngữ", ["Tiếng Việt", "English"])
vi = lang == "Tiếng Việt"
def _(vi_text, en_text):
    return vi_text if vi else en_text

# -----------------------
# Header / Logo
# -----------------------
now = datetime.now(vn_tz)
try:
    st.image(Image.open("logo1.png"), width=1200)
except:
    pass
st.markdown(f"<h2 style='text-align:center'>🌾 {_('Hệ thống tưới tiêu nông nghiệp thông minh','Smart Agricultural Irrigation System')} 🌾</h2>", unsafe_allow_html=True)
st.markdown(f"<h4 style='text-align:center'>{now.strftime('%d/%m/%Y %H:%M:%S')}</h4>", unsafe_allow_html=True)

# -----------------------
# Sidebar: role & auth
# -----------------------
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
# Locations & crops (simple)
# -----------------------
locations = {
    "TP. Hồ Chí Minh": (10.762622, 106.660172),
    "Hà Nội": (21.028511, 105.804817),
    "Cần Thơ": (10.045161, 105.746857),
}
location_names = {k: _(k, k) for k in locations.keys()}  # same text for both languages in this simple example
selected_city_display = st.selectbox(_("📍 Chọn địa điểm:", "📍 Select location:"), [location_names[k] for k in locations.keys()])
selected_city = next(k for k, v in location_names.items() if v == selected_city_display)

crops = {"Ngô": 65, "Chuối": 70, "Ớt": 65}
crop_names = {k: _(k, k) for k in crops.keys()}

# -----------------------
# Crop management
# -----------------------
st.header(_("🌱 Quản lý cây trồng", "🌱 Crop Management"))
mode_flag = config.get("mode", "auto")

if user_type == _("Người điều khiển", "Control Administrator"):
    st.subheader(_("Thêm / Cập nhật vùng trồng", "Add / Update Plantings"))
    multiple = st.checkbox(_("Trồng nhiều loại trên khu vực này", "Plant multiple crops in this location"), value=False)
    if selected_city not in crop_data:
        crop_data[selected_city] = {"plots": []}
    if multiple:
        col1, col2 = st.columns([2,1])
        with col1:
            add_crop = st.selectbox(_("Chọn loại cây để thêm", "Select crop to add"), [crop_names[k] for k in crops.keys()])
            add_crop_key = next(k for k,v in crop_names.items() if v == add_crop)
            add_planting_date = st.date_input(_("Ngày gieo trồng", "Planting date for this crop"), value=date.today())
        with col2:
            if st.button(_("➕ Thêm cây", "➕ Add crop")):
                crop_data[selected_city]["plots"].append({"crop": add_crop_key, "planting_date": add_planting_date.isoformat()})
                save_json(DATA_FILE, crop_data)
                st.success(_("Đã thêm cây vào khu vực.", "Crop added to location."))
    else:
        crop_display_names = [crop_names[k] for k in crops.keys()]
        selected_crop_display = st.selectbox(_("🌱 Chọn loại nông sản:", "🌱 Select crop type:"), crop_display_names)
        selected_crop = next(k for k,v in crop_names.items() if v == selected_crop_display)
        planting_date = st.date_input(_("📅 Ngày gieo trồng:", "📅 Planting date:"), value=date.today())
        if st.button(_("💾 Lưu thông tin trồng", "💾 Save planting info")):
            crop_data[selected_city] = {"plots": [{"crop": selected_crop, "planting_date": planting_date.isoformat()}]}
            save_json(DATA_FILE, crop_data)
            st.success(_("Đã lưu thông tin trồng.", "Planting info saved."))

else:
    st.subheader(_("Thông tin cây trồng tại khu vực", "Plantings at this location"))
    if selected_city in crop_data and crop_data[selected_city].get("plots"):
        rows = []
        for p in crop_data[selected_city]["plots"]:
            crop_k = p["crop"]
            pd_iso = p.get("planting_date", date.today().isoformat())
            try:
                pd_date = date.fromisoformat(pd_iso)
            except:
                pd_date = date.today()
            min_d, max_d = (0,0)
            if crop_k in ["Ngô","Chuối","Ớt"]:
                # reuse earlier ranges if desired; here just display planting info
                min_d, max_d = (0,0)
            days_planted = (date.today() - pd_date).days
            rows.append({
                "crop": crop_names.get(crop_k, crop_k),
                "planting_date": pd_date.strftime("%d/%m/%Y"),
                "days_planted": days_planted,
            })
        st.dataframe(pd.DataFrame(rows))
    else:
        st.info(_("📍 Chưa có thông tin gieo trồng tại khu vực này.", "📍 No crop information available in this location."))

# -----------------------
# System config: Auto/Manual + watering schedule
# -----------------------
st.header(_("⚙️ Cấu hình chung hệ thống", "⚙️ System General Configuration"))

col1, col2 = st.columns(2)
with col1:
    st.markdown(_("### ⏲️ Khung giờ tưới nước", "### ⏲️ Watering time window"))
    try:
        start_time = st.time_input(_("Giờ bắt đầu", "Start time"),
            value=datetime.strptime(config["watering_schedule"].split("-")[0], "%H:%M").time())
        end_time = st.time_input(_("Giờ kết thúc", "End time"),
            value=datetime.strptime(config["watering_schedule"].split("-")[1], "%H:%M").time())
    except Exception:
        # fallback to defaults
        start_time = st.time_input(_("Giờ bắt đầu", "Start time"), value=time(6,0))
        end_time = st.time_input(_("Giờ kết thúc", "End time"), value=time(8,0))
with col2:
    st.markdown(_("### 🔄 Chọn chế độ", "### 🔄 Select operation mode"))
    main_mode = st.radio(
        _("Chọn chế độ điều khiển", "Select control mode"),
        [_("Tự động", "Automatic"), _("Thủ công", "Manual")],
        index=0 if config.get("mode", "auto") == "auto" else 1,
    )

if st.button(_("💾 Lưu cấu hình", "💾 Save configuration")):
    config["watering_schedule"] = f"{start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')}"
    config["mode"] = "auto" if main_mode == _("Tự động","Automatic") else "manual"
    save_json(CONFIG_FILE, config)
    st.success(_("Đã lưu cấu hình.", "Configuration saved."))

# helper: check watering time (supports overnight ranges)
def check_in_watering_time():
    now_t = datetime.now(vn_tz).time()
    s_str, e_str = config.get("watering_schedule", "06:00-08:00").split("-")
    s = datetime.strptime(s_str, "%H:%M").time()
    e = datetime.strptime(e_str, "%H:%M").time()
    if s <= e:
        return s <= now_t <= e
    else:
        # overnight window
        return now_t >= s or now_t <= e

# -----------------------
# Weather widget (unchanged)
# -----------------------
st.subheader(_("🌦️ Thời tiết hiện tại", "🌦️ Current Weather"))
latitude, longitude = locations[selected_city]
weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}&current=temperature_2m,relative_humidity_2m,precipitation,precipitation_probability&timezone=auto"
try:
    response = requests.get(weather_url, timeout=10)
    response.raise_for_status()
    weather_data = response.json()
    current_weather = weather_data.get("current", {})
except Exception as e:
    current_weather = {"temperature_2m": "N/A", "relative_humidity_2m": "N/A", "precipitation": "N/A", "precipitation_probability": "N/A"}

col1, col2, col3 = st.columns(3)
col1.metric("🌡️ " + _("Nhiệt độ", "Temperature"), f"{current_weather.get('temperature_2m', 'N/A')} °C")
col2.metric("💧 " + _("Độ ẩm", "Humidity"), f"{current_weather.get('relative_humidity_2m', 'N/A')} %")
col3.metric("☔ " + _("Khả năng mưa", "Precipitation Prob."), f"{current_weather.get('precipitation_probability', 'N/A')} %")

# -----------------------
# Remove any simulation: ensure no simulated sensor data present
# (We will only accept MQTT or HTTP POST)
# -----------------------

# -----------------------
# MQTT client to receive data (optional, also accept HTTP POST)
# -----------------------
MQTT_BROKER = "test.mosquitto.org"
MQTT_PORT = 1883
TOPIC_DATA = "smart_irrigation/sensor_data"
TOPIC_COMMAND = "smart_irrigation/command"

mqtt_client = mqtt.Client()
mqtt_connected_flag = False
mqtt_lock = threading.Lock()
latest_values = {"soil_moisture": None, "soil_temp": None, "water_flow": None, "pump_manual": False}

def mqtt_on_connect(client, userdata, flags, rc):
    global mqtt_connected_flag
    if rc == 0:
        mqtt_connected_flag = True
        client.subscribe(TOPIC_DATA)
        print("MQTT connected, subscribed to", TOPIC_DATA)
    else:
        print("MQTT failed to connect, rc=", rc)

def mqtt_on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload.decode())
        # expected fields: soil_moisture, soil_temp, water_flow, pump_manual (optional)
        soil = data.get("soil_moisture")
        temp = data.get("soil_temp")
        flow = data.get("water_flow")
        pump_manual = data.get("pump_manual", False)
        with mqtt_lock:
            if soil is not None:
                latest_values["soil_moisture"] = float(soil)
            if temp is not None:
                latest_values["soil_temp"] = float(temp)
            if flow is not None:
                latest_values["water_flow"] = float(flow)
            latest_values["pump_manual"] = bool(pump_manual)
        # save to history
        if soil is not None and temp is not None:
            add_history_record(float(soil), float(temp))
        if flow is not None:
            add_flow_record(float(flow))
    except Exception as e:
        print("Error processing MQTT message:", e)

mqtt_client.on_connect = mqtt_on_connect
mqtt_client.on_message = mqtt_on_message

def mqtt_loop():
    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_forever()
    except Exception as e:
        print("MQTT connection error:", e)

# start mqtt thread
threading.Thread(target=mqtt_loop, daemon=True).start()

# -----------------------
# Flask API to accept HTTP POST from ESP32
# -----------------------
app = Flask(__name__)

@app.route("/esp32/data", methods=["POST"])
def esp32_data():
    """
    Accept JSON:
    {
      "soil_moisture": 55.3,
      "soil_temp": 29.6,
      "water_flow": 1.2,
      "pump_manual": false
    }
    """
    try:
        data = request.get_json(force=True)
        soil = data.get("soil_moisture")
        temp = data.get("soil_temp")
        flow = data.get("water_flow")
        pump_manual = data.get("pump_manual", False)
        if soil is not None and temp is not None:
            add_history_record(float(soil), float(temp))
        if flow is not None:
            add_flow_record(float(flow))
        # also update latest_values in app
        with mqtt_lock:
            if soil is not None:
                latest_values["soil_moisture"] = float(soil)
            if temp is not None:
                latest_values["soil_temp"] = float(temp)
            if flow is not None:
                latest_values["water_flow"] = float(flow)
            latest_values["pump_manual"] = bool(pump_manual)
        return jsonify({"status":"ok"}), 200
    except Exception as e:
        return jsonify({"status":"error","error":str(e)}), 400

def flask_thread():
    # runs on port 5001 by default
    app.run(host="0.0.0.0", port=5001, debug=False, use_reloader=False)

threading.Thread(target=flask_thread, daemon=True).start()

# -----------------------
# Show real-time latest values
# -----------------------
st.header(_("📡 Dữ liệu cảm biến thực tế", "📡 Real sensor data"))

with mqtt_lock:
    lv = latest_values.copy()

if lv["soil_moisture"] is None or lv["soil_temp"] is None:
    st.warning(_("Chưa nhận được dữ liệu cảm biến từ ESP32.", "No sensor data received from ESP32 yet."))
else:
    st.metric(_("Độ ẩm đất hiện tại", "Current soil moisture"), f"{lv['soil_moisture']:.1f}%")
    st.metric(_("Nhiệt độ đất hiện tại", "Current soil temperature"), f"{lv['soil_temp']:.1f}°C")

if lv["water_flow"] is None:
    st.info(_("Chưa có dữ liệu lưu lượng nước.", "No water flow data yet."))
else:
    st.metric(_("Lưu lượng nước hiện tại", "Current water flow"), f"{lv['water_flow']:.2f} L/min")

st.markdown(f"**{_('Trạng thái bơm thủ công (ESP32 báo)', 'Manual pump status reported by ESP32')}:** {lv['pump_manual']}")

# -----------------------
# Historical charts by date (robust datetime handling)
# -----------------------
st.header(_("📊 Biểu đồ lịch sử độ ẩm, nhiệt độ và lưu lượng (chọn ngày)", "📊 Historical charts (choose date)"))

chart_date = st.date_input(_("Chọn ngày để xem dữ liệu", "Select date for chart"), value=date.today())

# reload files (in case updated by MQTT/HTTP threads)
history_data = load_json(HISTORY_FILE, [])
flow_data = load_json(FLOW_FILE, [])

def parse_and_localize_timestamp(df, col):
    if df.empty:
        return df
    df[col] = pd.to_datetime(df[col], errors="coerce")
    df = df.dropna(subset=[col])
    # if tz-naive, assume stored as ISO without tz -> treat as UTC then convert
    if df[col].dt.tz is None:
        df[col] = df[col].dt.tz_localize('UTC').dt.tz_convert(vn_tz)
    else:
        df[col] = df[col].dt.tz_convert(vn_tz)
    return df

df_hist_all = pd.DataFrame(history_data)
if not df_hist_all.empty and 'timestamp' in df_hist_all.columns:
    df_hist_all = parse_and_localize_timestamp(df_hist_all, 'timestamp')
    df_hist_all['date'] = df_hist_all['timestamp'].dt.date
    df_day = df_hist_all[df_hist_all['date'] == chart_date]
else:
    df_day = pd.DataFrame()

df_flow_all = pd.DataFrame(flow_data)
if not df_flow_all.empty and 'time' in df_flow_all.columns:
    df_flow_all = parse_and_localize_timestamp(df_flow_all, 'time')
    df_flow_all['date'] = df_flow_all['time'].dt.date
    df_flow_day = df_flow_all[df_flow_all['date'] == chart_date]
else:
    df_flow_day = pd.DataFrame()

if df_day.empty and df_flow_day.empty:
    st.info(_("📋 Không có dữ liệu lịch sử trong ngày này.", "📋 No historical data for this date."))
else:
    # plot soil moisture & soil temp together (dual y)
    if not df_day.empty:
        fig, ax1 = plt.subplots(figsize=(12,4))
        ax1.plot(df_day['timestamp'], df_day['sensor_hum'], '-', label=_("Độ ẩm đất", "Soil moisture"))
        ax1.set_xlabel(_("Thời gian", "Time"))
        ax1.set_ylabel(_("Độ ẩm đất (%)", "Soil moisture (%)"), color='tab:blue')
        ax1.tick_params(axis='y', labelcolor='tab:blue')
        ax2 = ax1.twinx()
        ax2.plot(df_day['timestamp'], df_day['sensor_temp'], '-', label=_("Nhiệt độ đất", "Soil temperature"), color='tab:red')
        ax2.set_ylabel(_("Nhiệt độ (°C)", "Temperature (°C)"), color='tab:red')
        ax2.tick_params(axis='y', labelcolor='tab:red')
        ax1.legend(loc='upper left')
        ax2.legend(loc='upper right')
        plt.title(_("Lịch sử độ ẩm đất và nhiệt độ", "Soil moisture & temperature history"))
        plt.xticks(rotation=45)
        plt.tight_layout()
        st.pyplot(fig)
    else:
        st.info(_("Không có dữ liệu độ ẩm/nhiệt độ trong ngày này.", "No soil moisture/temp data for this date."))

    # plot water flow
    if not df_flow_day.empty:
        fig2, ax3 = plt.subplots(figsize=(12,3))
        ax3.plot(df_flow_day['time'], df_flow_day['flow'], '-', label=_("Lưu lượng nước (L/min)", "Water flow (L/min)"), color='tab:green')
        ax3.set_xlabel(_("Thời gian", "Time"))
        ax3.set_ylabel(_("Lưu lượng (L/min)", "Flow (L/min)"))
        ax3.legend()
        plt.title(_("Lịch sử lưu lượng nước", "Water flow history"))
        plt.xticks(rotation=45)
        plt.tight_layout()
        st.pyplot(fig2)
    else:
        st.info(_("Không có dữ liệu lưu lượng nước trong ngày này.", "No water flow data for this date."))

# -----------------------
# Irrigation decision & pump control
# -----------------------
st.header(_("💧 Quyết định tưới & điều khiển bơm", "Irrigation decision & pump control"))

# get crop threshold
soil_moisture_standard = 65
if selected_city in crop_data and crop_data[selected_city].get("plots"):
    crop_k = crop_data[selected_city]["plots"][0].get("crop")
    soil_moisture_standard = crops.get(crop_k, 65)

# last known measured humidity (prefer history file last record)
last_soil = None
if df_hist_all is not None and not df_hist_all.empty:
    last_soil = df_hist_all.iloc[-1]['sensor_hum']
elif lv.get("soil_moisture") is not None:
    last_soil = lv.get("soil_moisture")

st.markdown(f"- {_('Loại cây hiện tại', 'Current crop')}: **{crop_k if selected_city in crop_data else _('Chưa chọn', 'Not selected')}**")
st.markdown(f"- {_('Độ ẩm chuẩn', 'Soil moisture standard')}: **{soil_moisture_standard}%**")
st.markdown(f"- {_('Độ ẩm hiện tại', 'Current soil moisture')}: **{last_soil if last_soil is not None else _('Không có dữ liệu', 'No data')}**")

auto_should_water = False
if config.get("mode","auto") == "auto":
    if last_soil is None:
        st.warning(_("⚠️ Không có dữ liệu độ ẩm để quyết định.", "⚠️ No soil moisture data to decide."))
    else:
        # "thấp hơn nhiều": dùng 80% của chuẩn (bạn có thể thay ngưỡng)
        threshold_trigger = soil_moisture_standard * 0.8
        if check_in_watering_time() and last_soil < threshold_trigger:
            auto_should_water = True
            st.warning(_("Độ ẩm thấp hơn ngưỡng, hệ thống sẽ gửi lệnh bật bơm (auto).", "Soil moisture below threshold — auto pump command will be sent."))
        else:
            st.info(_("Không cần tưới theo điều kiện hiện tại.", "No irrigation needed based on current conditions."))
else:
    st.info(_("Chế độ thủ công: hệ thống sẽ không tự gửi lệnh bật bơm.", "Manual mode: system will not auto-send pump commands."))

# send MQTT command if in auto and pump should be on
if config.get("mode","auto") == "auto":
    try:
        mqtt_client.publish(TOPIC_COMMAND, json.dumps({"pump": "on" if auto_should_water else "off"}))
        st.markdown(f"**{_('Lệnh gửi', 'Command sent')}:** {'ON' if auto_should_water else 'OFF'}")
    except Exception as e:
        st.error(_("Lỗi gửi lệnh MQTT:", "Error sending MQTT command:") + str(e))

# -----------------------
# Footer
# -----------------------
st.markdown("---")
st.caption(_("API POST cho ESP32: POST /esp32/data JSON với soil_moisture, soil_temp, water_flow, pump_manual", "HTTP POST endpoint for ESP32: /esp32/data (JSON)"))
st.caption(_("MQTT topic nhận dữ liệu: smart_irrigation/sensor_data | gửi lệnh: smart_irrigation/command", "MQTT topic receive: smart_irrigation/sensor_data | command: smart_irrigation/command"))
st.caption(_("Người thực hiện: Ngô Nguyễn Định Tường - Mai Phúc Khang", "Author: ..."))
