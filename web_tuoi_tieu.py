# web_esp.py
import streamlit as st
from datetime import datetime, timedelta, date, time
import random
from PIL import Image
import requests
import json
import os
from streamlit_autorefresh import st_autorefresh
import pytz
import pandas as pd

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
        start_time = st.time_input(_("Giờ bắt đầu", "Start time"), value=datetime.strptime(config["watering_schedule"].split("-")[0], "%H:%M").time())
        end_time = st.time_input(_("Giờ kết thúc", "End time"), value=datetime.strptime(config["watering_schedule"].split("-")[1], "%H:%M").time())
    with col2:
        st.markdown(_("### 🔄 Chế độ hoạt động", "### 🔄 Operation mode"))
        mode_sel = st.radio(_("Chọn chế độ", "Select mode"), [_("Auto", "Auto"), _("Manual", "Manual")], index=0 if config.get("mode","auto")=="auto" else 1)

    if st.button(_("💾 Lưu cấu hình", "💾 Save configuration")):
        # Save to config.json
        config["watering_schedule"] = f"{start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')}"
        config["mode"] = "auto" if mode_sel == _("Auto", "Auto") else "manual"
        save_json(CONFIG_FILE, config)
        st.success(_("Đã lưu cấu hình.", "Configuration saved."))

else:
    st.markdown(_("⏲️ Khung giờ tưới nước hiện tại:", "⏲️ Current watering time window:") + f" **{config['watering_schedule']}**")
    st.markdown(_("🔄 Chế độ hoạt động hiện tại:", "🔄 Current operation mode:") + f" **{config['mode'].capitalize()}**")

mode_flag = config.get("mode", "auto")

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
col1.metric("🌡️ " + _("Nhiệt độ", "Temperature"), f"{current_weather.get('temperature_2m', 'N/A')} °C")
col2.metric("💧 " + _("Độ ẩm", "Humidity"), f"{current_weather.get('relative_humidity_2m', 'N/A')} %")
col3.metric("☔ " + _("Khả năng mưa", "Precipitation Prob."), f"{current_weather.get('precipitation_probability', 'N/A')} %")

# -----------------------
# Sensor Data Simulation (for demo)
# -----------------------
st.subheader(_("📡 Dữ liệu cảm biến (mô phỏng)", "📡 Sensor Data (Simulated)"))
simulated_soil_moisture = random.randint(40, 80)
simulated_light = random.randint(100, 1000)
simulated_water_flow = random.randint(0, 100)

st.write(f"{_('Độ ẩm đất (sim)', 'Soil Moisture (sim)')}: {simulated_soil_moisture}%")
st.write(f"{_('Ánh sáng (sim)', 'Light (sim)')}: {simulated_light} lux")
st.write(f"{_('Lưu lượng nước (sim)', 'Water Flow (sim)')}: {simulated_water_flow} L/min")

# -----------------------
# Check watering schedule and mode for irrigation decision
# -----------------------
st.header(_("🚿 Quyết định tưới nước", "🚿 Irrigation decision"))

start_str, end_str = config["watering_schedule"].split("-")
start_watering = datetime.combine(date.today(), datetime.strptime(start_str, "%H:%M").time()).replace(tzinfo=vn_tz)
end_watering = datetime.combine(date.today(), datetime.strptime(end_str, "%H:%M").time()).replace(tzinfo=vn_tz)

now_vn = datetime.now(vn_tz)

is_in_watering_time = start_watering <= now_vn <= end_watering

if is_in_watering_time:
    st.success(_("⏰ Hiện tại đang trong khung giờ tưới.", "⏰ Currently within watering schedule."))
else:
    st.info(_("⏰ Hiện tại không phải khung giờ tưới.", "⏰ Currently outside watering schedule."))

if mode_flag == "manual":
    st.info(_("⚠️ Chế độ tưới thủ công đang bật, cần xác nhận bật bơm.", "⚠️ Manual mode is ON, pump activation requires confirmation."))

    if is_in_watering_time:
        if "pump_confirmed" not in st.session_state:
            st.session_state.pump_confirmed = False
        if not st.session_state.pump_confirmed:
            st.warning(_("❗ Vui lòng xác nhận bật bơm trong vòng 5 phút.", "❗ Please confirm to turn on pump within 5 minutes."))

            col_confirm, col_cancel = st.columns(2)
            with col_confirm:
                if st.button(_("✅ Đồng ý bật bơm", "✅ Confirm to turn on pump")):
                    st.session_state.pump_confirmed = True
                    st.success(_("🚰 Bơm đã được bật!", "🚰 Pump is ON!"))
                    # TODO: Gửi lệnh bật bơm tới ESP32-WROOM
            with col_cancel:
                if st.button(_("❌ Hủy bật bơm", "❌ Cancel pump activation")):
                    st.session_state.pump_confirmed = False
                    st.info(_("Bơm không được bật.", "Pump is NOT turned on."))

        else:
            st.success(_("🚰 Bơm đang hoạt động.", "🚰 Pump is running."))

else:
    # Auto mode
    if is_in_watering_time:
        st.success(_("🚿 Hệ thống tự động tưới trong khung giờ này.", "🚿 System is auto-watering during this schedule."))
        # TODO: logic tưới tự động, gửi lệnh bật bơm tới ESP32-WROOM

    else:
        st.info(_("🚿 Hệ thống không tưới ngoài khung giờ.", "🚿 System does not water outside schedule."))

# -----------------------
# Lịch sử tưới nước (unchanged)
# -----------------------
st.header(_("📜 Lịch sử tưới nước", "📜 Irrigation History"))
if history_data:
    df_hist = pd.DataFrame(history_data)
    st.dataframe(df_hist)
else:
    st.info(_("Chưa có dữ liệu lịch sử tưới.", "No irrigation history data."))

# -----------------------
# Charts (Requirement 5 & 6)
# - 5: comparison values as line chart (Ox=hour, Oy=value), selectable by date (from saved history)
# - 6: line chart of water flow from flow_data.json (Ox=hour, Oy=flow), selectable by date
# Update every 20 minutes (we set st_autorefresh earlier when in_compare_time)
# -----------------------
st.header(_("📊 Biểu đồ phân tích", "📊 Analysis Charts"))

# pick date for charts
chart_date = st.date_input(_("Chọn ngày để xem lịch sử (Biểu đồ)", "Choose date for charts"), value=date.today())

# prepare comparison chart data (we'll use history sensor values)
df_hist_all = pd.DataFrame(history_data) if history_data else pd.DataFrame()
if not df_hist_all.empty:
    # filter by date
    df_hist_all['date'] = pd.to_datetime(df_hist_all['timestamp']).dt.date
    df_day = df_hist_all[df_hist_all['date'] == chart_date]
    if not df_day.empty:
        # build times as x and values (we'll plot sensor_hum and temperature)
        df_day['time_h'] = pd.to_datetime(df_day['timestamp']).dt.strftime("%H:%M:%S")
        st.subheader(_("So sánh: Độ ẩm và Nhiệt độ theo thời gian", "Comparison: Humidity and Temperature over time"))
        chart_df = df_day.set_index('time_h')[['sensor_hum','sensor_temp']].sort_index()
        st.line_chart(chart_df)
    else:
        st.info(_("Không có dữ liệu lịch sử cho ngày này.", "No history data for this date."))
else:
    st.info(_("Chưa có dữ liệu lịch sử để vẽ biểu đồ.", "No history data to plot."))

# flow chart
flow_df_all = pd.DataFrame(flow_data) if flow_data else pd.DataFrame()
if not flow_df_all.empty:
    flow_df_all['date'] = pd.to_datetime(flow_df_all['time']).dt.date
    flow_day = flow_df_all[flow_df_all['date'] == chart_date]
    if not flow_day.empty:
        flow_day['time_h'] = pd.to_datetime(flow_day['time']).dt.strftime("%H:%M:%S")
        st.subheader(_("📈 Lưu lượng nước tưới theo giờ", "📈 Water Flow over time"))
        flow_chart_df = flow_day.set_index('time_h')[['flow']].sort_index()
        st.line_chart(flow_chart_df)
    else:
        st.info(_("Không có dữ liệu lưu lượng cho ngày này.", "No flow data for this date."))
else:
    st.info(_("Chưa có dữ liệu lưu lượng nước.", "No water flow data available."))

# -----------------------
# Footer
# -----------------------
st.markdown("---")
st.caption("📡 API thời tiết: Open-Meteo | Dữ liệu cảm biến: ESP32-WROOM (giả lập nếu chưa có)")
st.caption("Người thực hiện: Ngô Nguyễn Định Tường-Mai Phúc Khang")




