# web_esp.py
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

# -----------------------
# Cấu hình & helper
# -----------------------
st.set_page_config(page_title="Smart Irrigation WebApp", layout="wide")
st_autorefresh(interval=60 * 1000, key="init_refresh")

lang = st.sidebar.selectbox("🌐 Language / Ngôn ngữ", ["Tiếng Việt", "English"])
vi = lang == "Tiếng Việt"
def _(vi_text, en_text):
    return vi_text if vi else en_text

DATA_FILE = "crop_data.json"
HISTORY_FILE = "history_irrigation.json"
CONFIG_FILE = "config.json"
WATER_FLOW_FILE = "water_flow_history.json"

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

crop_data = load_json(DATA_FILE, {})
history_data = load_json(HISTORY_FILE, [])
config = load_json(CONFIG_FILE, {"watering_schedule": "06:00-08:00", "mode": "auto"})
water_flow_history = load_json(WATER_FLOW_FILE, {})  # key: "YYYY-MM-DD" -> list of flow values

now = datetime.now(vn_tz)

try:
    st.image(Image.open("logo1.png"), width=1200)
except:
    st.warning(_("Không tìm thấy logo1.png", "logo1.png not found"))

st.markdown(f"<h2 style='text-align:center'>{_('Hệ thống tưới tiêu nông nghiệp thông minh', 'Smart Agricultural Irrigation System')}</h2>", unsafe_allow_html=True)
st.markdown(f"<h3 style='text-align:center'>{now.strftime('%d/%m/%Y %H:%M:%S')}</h3>", unsafe_allow_html=True)

st.sidebar.title(_("Chọn vai trò người dùng", "Select user role"))
user_type = st.sidebar.radio(_("Bạn là:", "You are:"), [_("Người điều khiển", "Controller"), _("Người giám sát", "Supervisor")])

if user_type == _("Người điều khiển", "Controller"):
    pwd = st.sidebar.text_input(_("Nhập mật khẩu:", "Enter password:"), type="password")
    if pwd != "admin123":
        st.sidebar.error(_("Mật khẩu sai. Truy cập bị từ chối.", "Incorrect password. Access denied."))
        st.stop()
    else:
        st.sidebar.success(_("Đăng nhập thành công.", "Login successful."))

locations = {
    "TP. Hồ Chí Minh": (10.762622, 106.660172),
    "Hà Nội": (21.028511, 105.804817),
    "Cần Thơ": (10.045161, 105.746857),
}
location_names = {
    "TP. Hồ Chí Minh": _("TP. Hồ Chí Minh", "Ho Chi Minh City"),
    "Hà Nội": _("Hà Nội", "Hanoi"),
    "Cần Thơ": _("Cần Thơ", "Can Tho"),
}
location_display_names = [location_names[k] for k in locations.keys()]
selected_city_display = st.selectbox(_("Chọn địa điểm:", "Select location:"), location_display_names)
selected_city = next(k for k, v in location_names.items() if v == selected_city_display)

crops = {
    "Ngô": 65,
    "Chuối": 70,
    "Ớt": 65,
}
crop_names = {"Ngô": _("Ngô", "Corn"), "Chuối": _("Chuối", "Banana"), "Ớt": _("Ớt", "Chili")}

st.header(_("Thông tin cây trồng", "Crop Information"))
if user_type == _("Người điều khiển", "Controller"):
    selected_crop = st.selectbox(_("Chọn cây trồng:", "Select crop:"), [crop_names[k] for k in crops.keys()])
    crop_key = next(k for k,v in crop_names.items() if v == selected_crop)
    planting_date = st.date_input(_("Ngày gieo trồng:", "Planting date:"), value=date.today())

    if st.button(_("Lưu thông tin cây trồng", "Save crop info")):
        crop_data[selected_city] = {"crop": crop_key, "planting_date": planting_date.isoformat()}
        save_json(DATA_FILE, crop_data)
        st.success(_("Đã lưu thông tin cây trồng.", "Crop info saved."))
elif user_type == _("Người giám sát", "Supervisor"):
    if selected_city in crop_data:
        cd = crop_data[selected_city]
        st.write(_("Loại cây:", "Crop:"), crop_names.get(cd.get("crop", ""), "-"))
        st.write(_("Ngày gieo trồng:", "Planting date:"), cd.get("planting_date", "-"))
    else:
        st.info(_("Chưa có dữ liệu cây trồng tại khu vực này.", "No crop data for this location."))

st.header(_("Cấu hình hệ thống", "System Configuration"))
watering_schedule = config.get("watering_schedule", "06:00-08:00")
mode = config.get("mode", "auto")

if user_type == _("Người điều khiển", "Controller"):
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(_("Khung giờ tưới (bắt đầu - kết thúc)", "Watering time window (start - end)"))
        start_time = st.time_input(_("Giờ bắt đầu", "Start time"), value=datetime.strptime(watering_schedule.split("-")[0], "%H:%M").time())
        end_time = st.time_input(_("Giờ kết thúc", "End time"), value=datetime.strptime(watering_schedule.split("-")[1], "%H:%M").time())
    with col2:
        st.markdown(_("Chọn chế độ", "Select mode"))
        mode_sel = st.radio(_("Chế độ điều khiển", "Control mode"), [_("Tự động", "Auto"), _("Thủ công", "Manual")], index=0 if mode=="auto" else 1)

    if st.button(_("Lưu cấu hình", "Save config")):
        config["watering_schedule"] = f"{start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')}"
        config["mode"] = "auto" if mode_sel == _("Tự động", "Auto") else "manual"
        save_json(CONFIG_FILE, config)
        st.success(_("Đã lưu cấu hình.", "Config saved."))
else:
    st.markdown(f"- {_('Khung giờ tưới:', 'Watering time window:')} **{watering_schedule}**")
    st.markdown(f"- {_('Chế độ hiện tại:', 'Current mode:')} **{_('Tự động', 'Auto') if mode=='auto' else _('Thủ công', 'Manual')}**")

current_time = datetime.now(vn_tz).time()
start_time_cfg = datetime.strptime(config["watering_schedule"].split("-")[0], "%H:%M").time()
end_time_cfg = datetime.strptime(config["watering_schedule"].split("-")[1], "%H:%M").time()

if start_time_cfg <= end_time_cfg:
    is_watering_time = start_time_cfg <= current_time <= end_time_cfg
else:
    is_watering_time = current_time >= start_time_cfg or current_time <= end_time_cfg

mqtt_broker = "broker.hivemq.com"
mqtt_port = 1883
mqtt_topic_humidity = "esp32/soil_humidity"
mqtt_topic_temperature = "esp32/soil_temperature"

mqtt_client = mqtt.Client()
sensor_data = {"soil_humidity": None, "soil_temperature": None}

def on_connect(client, userdata, flags, rc):
    print("MQTT connected with code " + str(rc))
    client.subscribe([(mqtt_topic_humidity, 0), (mqtt_topic_temperature, 0)])

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

    if sensor_data["soil_humidity"] is not None and sensor_data["soil_temperature"] is not None:
        history_data.append({
            "timestamp": datetime.now(vn_tz).isoformat(),
            "sensor_hum": sensor_data["soil_humidity"],
            "sensor_temp": sensor_data["soil_temperature"],
        })
        if len(history_data) > 100:
            history_data.pop(0)
        save_json(HISTORY_FILE, history_data)
        sensor_data["soil_humidity"] = None
        sensor_data["soil_temperature"] = None

def mqtt_loop():
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message
    mqtt_client.connect(mqtt_broker, mqtt_port, 60)
    mqtt_client.loop_forever()

if "mqtt_thread" not in st.session_state:
    thread = threading.Thread(target=mqtt_loop, daemon=True)
    thread.start()
    st.session_state["mqtt_thread"] = thread

st.header(_("Dữ liệu cảm biến từ ESP32", "Sensor Data from ESP32"))
if len(history_data) == 0:
    st.info(_("Chưa nhận được dữ liệu từ ESP32.", "No data received from ESP32 yet."))
else:
    df = pd.DataFrame(history_data)
    df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_convert(vn_tz)
    df = df.set_index("timestamp")
    st.line_chart(df[["sensor_hum", "sensor_temp"]].rename(columns={"sensor_hum": _("Độ ẩm đất (%)", "Soil Humidity (%)"), "sensor_temp": _("Nhiệt độ đất (°C)", "Soil Temperature (°C)")}))

st.header(_("Quyết định tưới nước", "Irrigation Decision"))
soil_moisture_standard = 65
if selected_city in crop_data and "crop" in crop_data[selected_city]:
    crop_key = crop_data[selected_city]["crop"]
    soil_moisture_standard = crops.get(crop_key, 65)

last_soil_humidity = None
if len(history_data) > 0:
    last_soil_humidity = history_data[-1]["sensor_hum"]

pump_status = False
should_water = False

if mode == "auto":
    if last_soil_humidity is not None:
        if last_soil_humidity < soil_moisture_standard * 0.8 and is_watering_time:
            should_water = True
            pump_status = True
            # Ghi lại lưu lượng nước cho ngày hôm nay - giả sử 10 lít mỗi lần tưới
            today_str = datetime.now(vn_tz).strftime("%Y-%m-%d")
            flow_amount = 10  # lít, giả sử
            if today_str not in water_flow_history:
                water_flow_history[today_str] = []
            water_flow_history[today_str].append({"timestamp": datetime.now(vn_tz).isoformat(), "flow": flow_amount})
            save_json(WATER_FLOW_FILE, water_flow_history)
        else:
            pump_status = False
    else:
        st.warning(_("Chưa có dữ liệu độ ẩm đất để quyết định tưới.", "No soil moisture data to decide irrigation."))
elif mode == "manual":
    pump_status = False

if mode == "auto":
    if should_water:
        st.warning(_("Tự động bật bơm do độ ẩm đất thấp hơn chuẩn.", "Auto pump ON due to low soil moisture."))
    else:
        st.info(_("Bơm đang tắt hoặc không cần bật.", "Pump OFF or no need to turn on."))
else:
    st.info(_("Chế độ thủ công: không tự bật bơm, bơm có thể được bật thủ công ngoài tủ điện.", "Manual mode: pump not auto controlled, may be manually controlled in cabinet."))

# Biểu đồ lưu lượng nước
st.header(_("Lịch sử lưu lượng nước theo ngày", "Daily Water Flow History"))

selected_date = st.date_input(_("Chọn ngày xem lưu lượng nước:", "Select date to view water flow:"), value=date.today())
selected_date_str = selected_date.strftime("%Y-%m-%d")

if selected_date_str in water_flow_history:
    flows = water_flow_history[selected_date_str]
    df_flow = pd.DataFrame(flows)
    df_flow["timestamp"] = pd.to_datetime(df_flow["timestamp"]).dt.tz_convert(vn_tz)
    df_flow = df_flow.set_index("timestamp")
    st.line_chart(df_flow["flow"].rename(_("Lưu lượng nước (lít)", "Water flow (liters)")))
else:
    st.info(_("Không có dữ liệu lưu lượng nước ngày này.", "No water flow data for this day."))


