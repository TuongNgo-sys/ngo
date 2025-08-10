# web_esp.py
import streamlit as st
from datetime import datetime, date, time, timedelta
from PIL import Image
import json, os, threading
import pytz
import pandas as pd
import matplotlib.pyplot as plt
import paho.mqtt.client as mqtt

# -----------------------
# Config & files
# -----------------------
st.set_page_config(page_title="Smart Irrigation WebApp", layout="wide")
try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=60 * 1000, key="refresh")
except:
    pass

DATA_FILE = "crop_data.json"
HISTORY_FILE = "history_irrigation.json"   # sensor history: timestamp, sensor_hum, sensor_temp
FLOW_FILE = "flow_data.json"                # flow history: time, flow
CONFIG_FILE = "config.json"

vn_tz = pytz.timezone("Asia/Ho_Chi_Minh")

# -----------------------
# Helpers: load/save JSON
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
# Record helpers (use VN timezone)
# -----------------------
def add_history_record(sensor_hum, sensor_temp):
    now_iso = datetime.now(vn_tz).isoformat()
    hist = load_json(HISTORY_FILE, [])
    hist.append({"timestamp": now_iso, "sensor_hum": sensor_hum, "sensor_temp": sensor_temp})
    save_json(HISTORY_FILE, hist)

def add_flow_record(flow_val):
    now_iso = datetime.now(vn_tz).isoformat()
    flows = load_json(FLOW_FILE, [])
    flows.append({"time": now_iso, "flow": flow_val})
    save_json(FLOW_FILE, flows)

# -----------------------
# Load persisted data
# -----------------------
crop_data = load_json(DATA_FILE, {})
history_data = load_json(HISTORY_FILE, [])
flow_data = load_json(FLOW_FILE, [])
config = load_json(CONFIG_FILE, {"watering_schedule": "06:00-08:00", "mode": "auto"})

# -----------------------
# i18n simple
# -----------------------
lang = st.sidebar.selectbox("🌐 Language / Ngôn ngữ", ["Tiếng Việt", "English"])
vi = lang == "Tiếng Việt"
def _(vi_text, en_text):
    return vi_text if vi else en_text

# -----------------------
# Header
# -----------------------
now = datetime.now(vn_tz)
try:
    st.image(Image.open("logo1.png"), width=1200)
except:
    pass
st.markdown(f"<h2 style='text-align:center'>🌾 {_('Hệ thống tưới tiêu nông nghiệp thông minh','Smart Agricultural Irrigation System')} 🌾</h2>", unsafe_allow_html=True)
st.markdown(f"<h4 style='text-align:center'>{now.strftime('%d/%m/%Y %H:%M:%S')}</h4>", unsafe_allow_html=True)

# -----------------------
# Role & auth
# -----------------------
st.sidebar.title(_("🔐 Chọn vai trò người dùng", "🔐 Select User Role"))
role = st.sidebar.radio(_("Bạn là:", "You are:"), [_("Người điều khiển", "Controller"), _("Người giám sát", "Supervisor")])

if role == _("Người điều khiển", "Controller"):
    pwd = st.sidebar.text_input(_("Nhập mật khẩu:", "Enter password:"), type="password")
    if pwd != "admin123":
        st.sidebar.error(_("Mật khẩu sai. Truy cập bị từ chối.", "Incorrect password. Access denied."))
        st.stop()
    else:
        st.sidebar.success(_("Xác thực thành công.", "Authentication successful."))

# -----------------------
# Locations & crop types
# -----------------------
locations = {
    "TP. Hồ Chí Minh": (10.762622, 106.660172),
    "Hà Nội": (21.028511, 105.804817),
    "Cần Thơ": (10.045161, 105.746857),
}
location_names = {k: _(k, k) for k in locations.keys()}
selected_city_display = st.selectbox(_("📍 Chọn địa điểm:", "📍 Select location:"), [location_names[k] for k in locations.keys()])
selected_city = next(k for k,v in location_names.items() if v == selected_city_display)

crops = {"Ngô": 65, "Chuối": 70, "Ớt": 65}
crop_names = {k: _(k,k) for k in crops.keys()}

# -----------------------
# Crop management (Controller can edit; Supervisor only view)
# -----------------------
st.header(_("🌱 Quản lý cây trồng", "🌱 Crop Management"))

if role == _("Người điều khiển", "Controller"):
    edit = st.checkbox(_("Chỉnh sửa thông tin trồng cây", "Edit planting info"))
    if edit:
        crop_choice = st.selectbox(_("Chọn loại cây:", "Select crop:"), [crop_names[k] for k in crops.keys()])
        crop_key = next(k for k,v in crop_names.items() if v == crop_choice)
        planting_date = st.date_input(_("Ngày gieo trồng:", "Planting date:"), value=date.today())
        if st.button(_("Lưu thông tin trồng", "Save planting info")):
            crop_data[selected_city] = {"plots":[{"crop": crop_key, "planting_date": planting_date.isoformat()}]}
            save_json(DATA_FILE, crop_data)
            st.success(_("Lưu thông tin thành công.", "Planting info saved."))
    # show current planting if exists
    if selected_city in crop_data and crop_data[selected_city].get("plots"):
        st.markdown(_("Thông tin hiện tại:", "Current planting:"))
        st.write(crop_data[selected_city]["plots"])
    else:
        st.info(_("Chưa có dữ liệu trồng ở khu vực này.", "No planting data for this location."))
else:
    # Supervisor view: only show planting history and location (handled below too)
    if selected_city in crop_data and crop_data[selected_city].get("plots"):
        st.markdown(_("📋 Lịch sử trồng:", "Planting history:"))
        st.dataframe(pd.DataFrame(crop_data[selected_city]["plots"]))
    else:
        st.info(_("Chưa có dữ liệu trồng ở khu vực này.", "No planting data for this location."))

# -----------------------
# System configuration (Controller only)
# -----------------------
if role == _("Người điều khiển", "Controller"):
    st.header(_("⚙️ Cấu hình hệ thống", "⚙️ System Configuration"))
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(_("### ⏲️ Khung giờ tưới nước", "### Watering time window"))
        try:
            start_time = st.time_input(_("Giờ bắt đầu", "Start time"),
                value=datetime.strptime(config["watering_schedule"].split("-")[0], "%H:%M").time())
            end_time = st.time_input(_("Giờ kết thúc", "End time"),
                value=datetime.strptime(config["watering_schedule"].split("-")[1], "%H:%M").time())
        except Exception:
            start_time = st.time_input(_("Giờ bắt đầu", "Start time"), value=time(6,0))
            end_time = st.time_input(_("Giờ kết thúc", "End time"), value=time(8,0))
    with col2:
        st.markdown(_("### 🔄 Chọn chế độ", "### Select mode"))
        mode_sel = st.radio(_("Chọn chế độ", "Mode"), [_("Tự động","Auto"), _("Thủ công","Manual")],
                             index=0 if config.get("mode","auto")=="auto" else 1)
    if st.button(_("💾 Lưu cấu hình", "Save config")):
        config["watering_schedule"] = f"{start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')}"
        config["mode"] = "auto" if mode_sel == _("Tự động","Auto") else "manual"
        save_json(CONFIG_FILE, config)
        st.success(_("Đã lưu cấu hình.", "Configuration saved."))
else:
    # Supervisor: show current config summary (read-only)
    st.markdown(_("⏲️ Khung giờ tưới hiện tại: ", "Watering time window: ") + f"**{config.get('watering_schedule')}**")
    st.markdown(_("🔄 Chế độ hiện tại: ", "Current mode: ") + f"**{_('Tự động','Auto') if config.get('mode','auto')=='auto' else _('Thủ công','Manual')}**")

# helper to check watering window (supports overnight)
def in_watering_window():
    now_t = datetime.now(vn_tz).time()
    s,e = config.get("watering_schedule","06:00-08:00").split("-")
    s_t = datetime.strptime(s, "%H:%M").time()
    e_t = datetime.strptime(e, "%H:%M").time()
    if s_t <= e_t:
        return s_t <= now_t <= e_t
    else:
        return now_t >= s_t or now_t <= e_t

# -----------------------
# Weather (unchanged)
# -----------------------
st.subheader(_("🌦️ Thời tiết hiện tại", "🌦️ Current Weather"))
lat, lon = locations[selected_city]
weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,precipitation,precipitation_probability&timezone=auto"
try:
    import requests
    resp = requests.get(weather_url, timeout=10); resp.raise_for_status()
    current_weather = resp.json().get("current", {})
except Exception:
    current_weather = {"temperature_2m":"N/A","relative_humidity_2m":"N/A","precipitation":"N/A","precipitation_probability":"N/A"}
c1,c2,c3 = st.columns(3)
c1.metric("🌡️ " + _("Nhiệt độ","Temperature"), f"{current_weather.get('temperature_2m','N/A')} °C")
c2.metric("💧 " + _("Độ ẩm","Humidity"), f"{current_weather.get('relative_humidity_2m','N/A')} %")
c3.metric("☔ " + _("Khả năng mưa","Precipitation Prob."), f"{current_weather.get('precipitation_probability','N/A')} %")

# -----------------------
# MQTT receiver (real data)
# -----------------------
MQTT_BROKER = "test.mosquitto.org"
MQTT_PORT = 1883
TOPIC_DATA = "smart_irrigation/sensor_data"
TOPIC_COMMAND = "smart_irrigation/command"

mqtt_client = mqtt.Client()
mqtt_lock = threading.Lock()
latest = {"soil_moisture": None, "soil_temp": None, "water_flow": None, "pump_manual": False}

def on_mqtt_connect(client, userdata, flags, rc):
    if rc == 0:
        client.subscribe(TOPIC_DATA)
        print("MQTT connected and subscribed")
    else:
        print("MQTT connect failed rc=", rc)

def on_mqtt_message(client, userdata, msg):
    try:
        payload = msg.payload.decode()
        data = json.loads(payload)
        soil = data.get("soil_moisture")
        temp = data.get("soil_temp")
        flow = data.get("water_flow")
        pump_manual = data.get("pump_manual", False)
        with mqtt_lock:
            if soil is not None: latest["soil_moisture"] = float(soil)
            if temp is not None: latest["soil_temp"] = float(temp)
            if flow is not None: latest["water_flow"] = float(flow)
            latest["pump_manual"] = bool(pump_manual)
        # store to history files
        if soil is not None and temp is not None:
            add_history_record(float(soil), float(temp))
        if flow is not None:
            add_flow_record(float(flow))
    except Exception as e:
        print("MQTT message error:", e)

mqtt_client.on_connect = on_mqtt_connect
mqtt_client.on_message = on_mqtt_message

def mqtt_worker():
    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_forever()
    except Exception as e:
        print("MQTT connection error:", e)

threading.Thread(target=mqtt_worker, daemon=True).start()

# -----------------------
# Show real-time latest (both roles see basic sensor values)
# -----------------------
st.header(_("📡 Dữ liệu cảm biến thực tế", "📡 Real sensor data"))
with mqtt_lock:
    lv = latest.copy()

if lv["soil_moisture"] is None or lv["soil_temp"] is None:
    st.warning(_("Chưa nhận được dữ liệu cảm biến từ ESP32.", "No sensor data received yet."))
else:
    st.metric(_("Độ ẩm đất hiện tại", "Current soil moisture"), f"{lv['soil_moisture']:.1f}%")
    st.metric(_("Nhiệt độ đất hiện tại", "Current soil temperature"), f"{lv['soil_temp']:.1f}°C")
if lv["water_flow"] is None:
    st.info(_("Chưa có dữ liệu lưu lượng.", "No water flow data yet."))
else:
    st.metric(_("Lưu lượng nước hiện tại", "Current water flow"), f"{lv['water_flow']:.2f} L/min")

# -----------------------
# Historical charts (Controller has full charts; Supervisor sees only watering history and planting)
# -----------------------
st.header(_("📊 Lịch sử & biểu đồ (chọn ngày)", "📊 History & charts (choose date)"))
chart_date = st.date_input(_("Chọn ngày để xem dữ liệu", "Select date for chart"), value=date.today())

# reload files
history_data = load_json(HISTORY_FILE, [])
flow_data = load_json(FLOW_FILE, [])

def parse_localize(df, col):
    if df.empty:
        return df
    df[col] = pd.to_datetime(df[col], errors="coerce")
    df = df.dropna(subset=[col])
    # if tz-naive, assume UTC then convert to VN tz
    if df[col].dt.tz is None:
        df[col] = df[col].dt.tz_localize("UTC").dt.tz_convert(vn_tz)
    else:
        df[col] = df[col].dt.tz_convert(vn_tz)
    return df

df_hist = pd.DataFrame(history_data)
if not df_hist.empty and 'timestamp' in df_hist.columns:
    df_hist = parse_localize(df_hist, 'timestamp')
    df_hist['date'] = df_hist['timestamp'].dt.date
    df_hist_day = df_hist[df_hist['date'] == chart_date]
else:
    df_hist_day = pd.DataFrame()

df_flow = pd.DataFrame(flow_data)
if not df_flow.empty and 'time' in df_flow.columns:
    df_flow = parse_localize(df_flow, 'time')
    df_flow['date'] = df_flow['time'].dt.date
    df_flow_day = df_flow[df_flow['date'] == chart_date]
else:
    df_flow_day = pd.DataFrame()

# Supervisor: show planting history, watering history (table), location
if role == _("Người giám sát", "Supervisor"):
    st.subheader(_("📍 Thông tin khu vực", "📍 Location info"))
    st.write(f"- {_('Địa điểm', 'Location')}: **{selected_city}**")
    st.subheader(_("📋 Lịch sử trồng", "Planting history"))
    if selected_city in crop_data and crop_data[selected_city].get("plots"):
        st.dataframe(pd.DataFrame(crop_data[selected_city]["plots"]))
    else:
        st.info(_("Không có lịch sử trồng.", "No planting history."))

    st.subheader(_("🚿 Lịch sử tưới (bảng) ", "Watering history (table)"))
    if not df_flow.empty:
        # show all flow history for selected city (we don't have city in flow records; showing all)
        st.dataframe(df_flow.sort_values(by='time', ascending=False).reset_index(drop=True))
    else:
        st.info(_("Không có lịch sử tưới.", "No watering history."))
    # end supervisor
    st.stop()

# Controller: show charts and controls
# soil charts
if df_hist_day.empty:
    st.info(_("Không có dữ liệu cảm biến trong ngày này.", "No sensor data for this date."))
else:
    fig, ax1 = plt.subplots(figsize=(12,4))
    ax1.plot(df_hist_day['timestamp'], df_hist_day['sensor_hum'], '-', label=_("Độ ẩm đất","Soil moisture"), color='tab:blue')
    ax1.set_ylabel("%", color='tab:blue')
    ax2 = ax1.twinx()
    ax2.plot(df_hist_day['timestamp'], df_hist_day['sensor_temp'], '-', label=_("Nhiệt độ đất","Soil temp"), color='tab:red')
    ax2.set_ylabel("°C", color='tab:red')
    ax1.set_xlabel(_("Thời gian", "Time"))
    ax1.legend(loc='upper left'); ax2.legend(loc='upper right')
    plt.title(_("Lịch sử độ ẩm & nhiệt độ", "Soil moisture & temperature history"))
    plt.xticks(rotation=45)
    plt.tight_layout()
    st.pyplot(fig)

# flow chart
if df_flow_day.empty:
    st.info(_("Không có dữ liệu lưu lượng trong ngày này.", "No flow data for this date."))
else:
    fig2, ax3 = plt.subplots(figsize=(12,3))
    ax3.plot(df_flow_day['time'], df_flow_day['flow'], '-', color='tab:green')
    ax3.set_xlabel(_("Thời gian", "Time")); ax3.set_ylabel(_("Lưu lượng (L)", "Flow (L)"))
    plt.title(_("Lịch sử lưu lượng nước", "Water flow history"))
    plt.xticks(rotation=45)
    plt.tight_layout()
    st.pyplot(fig2)

# -----------------------
# Irrigation decision & pump control (Controller only)
# -----------------------
st.header(_("💧 Quyết định tưới & điều khiển bơm", "Irrigation decision & pump control"))

if role != _("Người điều khiển", "Controller"):
    st.info(_("Bạn ở chế độ giám sát. Không có quyền điều khiển.", "You are in supervisor mode. No control permissions."))
    st.stop()

# Controller continues:
soil_standard = 65
if selected_city in crop_data and crop_data[selected_city].get("plots"):
    crop_k = crop_data[selected_city]["plots"][0].get("crop")
    soil_standard = crops.get(crop_k, 65)
last_soil_value = None
if not df_hist.empty:
    last_soil_value = df_hist.iloc[-1]['sensor_hum']
elif lv := latest.get("soil_moisture"):
    last_soil_value = lv

st.markdown(f"- {_('Loại cây hiện tại', 'Current crop')}: **{crop_k if 'crop_k' in locals() else _('Chưa chọn','Not selected')}**")
st.markdown(f"- {_('Độ ẩm chuẩn', 'Soil moisture standard')}: **{soil_standard}%**")
st.markdown(f"- {_('Độ ẩm hiện tại', 'Current soil moisture')}: **{last_soil_value if last_soil_value is not None else _('Không có dữ liệu','No data')}**")

auto_should = False
if config.get("mode","auto") == "auto":
    if last_soil_value is not None:
        trigger = soil_standard * 0.8
        if in_watering := in_watering_window() and last_soil_value < trigger:
            auto_should = True
            st.warning(_("Độ ẩm thấp hơn ngưỡng -> hệ thống sẽ gửi lệnh bật bơm (auto).", "Soil moisture below trigger -> will auto send pump ON."))
        else:
            st.info(_("Không cần tưới theo điều kiện hiện tại.", "No irrigation needed based on current conditions."))
    else:
        st.warning(_("Không có dữ liệu để quyết định.", "No data to decide."))
else:
    st.info(_("Chế độ thủ công: hệ thống sẽ không tự gửi lệnh.", "Manual mode: system will not auto-send commands."))

# send MQTT command if auto
try:
    mqtt_client.publish(TOPIC_COMMAND, json.dumps({"pump":"on" if auto_should else "off"}))
    st.markdown(f"**{_('Lệnh gửi', 'Command sent')}:** {'ON' if auto_should else 'OFF'}")
except Exception as e:
    st.error(_("Lỗi gửi lệnh MQTT:", "Error sending MQTT command: ") + str(e))

# manual control buttons (only for controller)
col_on, col_off = st.columns(2)
with col_on:
    if st.button(_("Bật bơm thủ công", "Turn ON pump manually")):
        mqtt_client.publish(TOPIC_COMMAND, json.dumps({"pump":"on"}))
        st.success(_("Đã gửi lệnh bật bơm", "Pump ON command sent"))
with col_off:
    if st.button(_("Tắt bơm thủ công", "Turn OFF pump manually")):
        mqtt_client.publish(TOPIC_COMMAND, json.dumps({"pump":"off"}))
        st.success(_("Đã gửi lệnh tắt bơm", "Pump OFF command sent"))

# -----------------------
# Footer
# -----------------------
st.markdown("---")
st.caption(_("MQTT topic nhận dữ liệu: smart_irrigation/sensor_data | gửi lệnh: smart_irrigation/command", "MQTT receive topic: smart_irrigation/sensor_data | command: smart_irrigation/command"))
st.caption(_("Tệp dữ liệu: crop_data.json, history_irrigation.json, flow_data.json, config.json", "Data files created in app folder"))
