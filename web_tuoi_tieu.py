# web_esp.py
import streamlit as st
from datetime import datetime, timedelta, date
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
# initial short refresh; will also call conditional refresh later
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

# load persistent data
crop_data = load_json(DATA_FILE, {})  # structure: {city: {"plots":[{crop,planting_date}], "irrigation_windows":[hours], "mode":"auto"/"manual"}}
history_data = load_json(HISTORY_FILE, [])  # list of records
flow_data = load_json(FLOW_FILE, [])  # list of {"time":"HH:MM:SS","city":..,"flow":value}

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
st.markdown(f"<h3>⏰ { _('Thời gian hiện tại', 'Current time') }:{now.strftime('%d:%m:%Y')}</h3>", unsafe_allow_html=True)

# -----------------------
# Sidebar - role, auth, mode
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

# Mode: Manual / Auto
mode = st.sidebar.radio(_("Chế độ hoạt động", "Operation mode"), [_("Auto", "Auto"), _("Manual", "Manual")])
mode_flag = "auto" if mode == _("Auto", "Auto") else "manual"

# LED indicator
led_color = "#00cc00" if mode_flag == "auto" else "#ff3333"
st.sidebar.markdown(f"<div><span class='led' style='background:{led_color}'></span> { _('Chế độ', 'Mode') }: <b>{mode}</b></div>", unsafe_allow_html=True)

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
# Control: add single/multiple crops (Requirement 1)
# -----------------------
st.header(_("🌱 Quản lý cây trồng", "🌱 Crop Management"))

if user_type == _("Người điều khiển", "Control Administrator"):
    st.subheader(_("Thêm / Cập nhật vùng trồng", "Add / Update Plantings"))
    multiple = st.checkbox(_("Trồng nhiều loại trên khu vực này", "Plant multiple crops in this location"), value=False)
    # initialize if not exists
    if selected_city not in crop_data:
        crop_data[selected_city] = {"plots": [], "irrigation_windows": [], "mode": mode_flag}
    # add crops
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
                crop_data[selected_city]["mode"] = mode_flag
                save_json(DATA_FILE, crop_data)
                st.success(_("Đã thêm cây vào khu vực.", "Crop added to location."))
    else:
        # single crop selection (original behavior)
        crop_display_names = [crop_names[k] for k in crops.keys()]
        selected_crop_display = st.selectbox(_("🌱 Chọn loại nông sản:", "🌱 Select crop type:"), crop_display_names)
        selected_crop = next(k for k, v in crop_names.items() if v == selected_crop_display)
        planting_date = st.date_input(_("📅 Ngày gieo trồng:", "📅 Planting date:"), value=date.today())
        if st.button(_("💾 Lưu thông tin trồng", "💾 Save planting info")):
            crop_data[selected_city] = {"plots": [{"crop": selected_crop, "planting_date": planting_date.isoformat()}],
                                        "irrigation_windows": crop_data.get(selected_city, {}).get("irrigation_windows", []),
                                        "mode": mode_flag}
            save_json(DATA_FILE, crop_data)
            st.success(_("Đã lưu thông tin trồng.", "Planting info saved."))

# Supervisor view of planted crops (Requirement 1 display multiple)
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
            # growth stage (reuse function below)
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

# reuse growth stage function for later
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
# Irrigation windows (Requirement 2)
# Each window is an hour value 0,2,4,...22 (every 2 hours)
# -----------------------
st.header(_("⏲️ Thiết lập khung giờ tưới", "⏲️ Irrigation Time Windows"))
hours = [f"{h:02d}:00" for h in range(0,24,2)]
selected_hours_display = crop_data.get(selected_city, {}).get("irrigation_windows", [])
# convert stored ints to display
selected_hours_display = [f"{h:02d}:00" for h in selected_hours_display] if selected_hours_display else []
chosen_hours = st.multiselect(_("Chọn khung giờ tưới (mỗi khung cách nhau 2 tiếng)", "Choose irrigation windows (every 2 hours)"), hours, default=selected_hours_display)
# save windows as ints
if st.button(_("💾 Lưu khung giờ tưới", "💾 Save irrigation windows")):
    ints = [int(h.split(":")[0]) for h in chosen_hours]
    if selected_city not in crop_data:
        crop_data[selected_city] = {"plots": [], "irrigation_windows": ints, "mode": mode_flag}
    else:
        crop_data[selected_city]["irrigation_windows"] = ints
        crop_data[selected_city]["mode"] = mode_flag
    save_json(DATA_FILE, crop_data)
    st.success(_("Đã lưu khung giờ tưới.", "Irrigation windows saved."))

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
col3.metric("🌧️ " + _("Mưa", "Rain"), f"{current_weather.get('precipitation', 'N/A')} mm")

# -----------------------
# Sensor data simulation (or get from ESP32)
# -----------------------
st.subheader(_("🧪 Dữ liệu cảm biến từ ESP32", "🧪 Sensor Data from ESP32"))
sensor_temp = round(random.uniform(25, 37), 1)
sensor_hum = round(random.uniform(50, 95), 1)
sensor_light = round(random.uniform(300, 1000), 1)
st.write(f"🌡️ { _('Nhiệt độ cảm biến', 'Sensor temperature') }: **{sensor_temp} °C**")
st.write(f"💧 { _('Độ ẩm đất cảm biến', 'Soil moisture') }: **{sensor_hum} %**")
st.write(f"☀️ { _('Cường độ ánh sáng', 'Light intensity') }: **{sensor_light} lux**")

# -----------------------
# Determine comparison time and refresh behavior (Requirement 3)
# Comparison windows defined by irrigation windows if set, else default (03:00-06:00 and 13:00-15:00)
# Refresh: in comparison window => 20 minutes, else 30 minutes
# Show history only in comparison window
# -----------------------
current_hour = now.hour
# check if we're in any user-selected irrigation window ±1 hour range for 'comparison' concept
user_windows = crop_data.get(selected_city, {}).get("irrigation_windows", [])
in_compare_time = False
if user_windows:
    # define compare windows as hour to hour+2 (same idea as earlier)
    for h in user_windows:
        if h <= current_hour < (h+2):
            in_compare_time = True
            break
else:
    # fallback to original comparison times
    in_compare_time = (3 <= current_hour < 6) or (13 <= current_hour < 15)

# apply conditional refresh (20 minutes = 1200s, 30 minutes = 1800s)
if in_compare_time:
    st_autorefresh(interval=20 * 60 * 1000, key=f"refresh_compare_{selected_city}")
else:
    st_autorefresh(interval=30 * 60 * 1000, key=f"refresh_outside_{selected_city}")

# -----------------------
# Comparison logic (Requirement 5 visualization later)
# -----------------------
st.subheader(_("🧠 So sánh dữ liệu cảm biến và thời tiết (theo khung giờ)", "🧠 Time-Based Comparison of Sensor and Weather Data"))

if in_compare_time:
    temp_diff = abs((current_weather.get("temperature_2m") or 0) - sensor_temp)
    hum_diff = abs((current_weather.get("relative_humidity_2m") or 0) - sensor_hum)
    if temp_diff < 2 and hum_diff < 10:
        st.success(_("✅ Cảm biến trùng khớp thời tiết trong khung giờ cho phép.", "✅ Sensor matches weather within allowed range."))
    else:
        st.warning(f"⚠️ { _('Sai lệch trong khung giờ', 'Deviation detected') }: {temp_diff:.1f}°C & {hum_diff:.1f}%")
else:
    st.info(_("⏱️ Hiện tại không trong khung giờ so sánh.", "⏱️ Outside comparison time window."))

# -----------------------
# Growth stage display (unchanged)
# -----------------------
st.subheader(_("📈 Giai đoạn phát triển cây", "📈 Plant Growth Stage"))
# display only primary plot if exists
plots = crop_data.get(selected_city, {}).get("plots", [])
if plots:
    # show first by default
    p0 = plots[0]
    try:
        planting_date = date.fromisoformat(p0["planting_date"])
        selected_crop = p0["crop"]
    except:
        planting_date = date.today()
        selected_crop = plots[0]["crop"]
    days_since = (date.today() - planting_date).days
    st.info(
        f"📅 { _('Đã trồng', 'Planted for') }: **{days_since} { _('ngày', 'days') }**\n\n"
        f"🌿 { _('Loại cây', 'Crop type') }: **{crop_names[selected_crop]}**\n\n"
        f"🔍 {giai_doan_cay(selected_crop, days_since)}"
    )
else:
    st.info(_("Chưa có cây trồng để hiển thị giai đoạn.", "No plantings to display growth stage."))

# -----------------------
# Irrigation decision & confirmation flow (Requirement 4 & 5)
# - If mode == auto, automatic requests lead to sending command (simulated) to ESP32.
# - If mode == manual, automatic requests are paused; controller must manually press to irrigate.
# - When controller is asked: show accept/reject; if accept -> record and do not re-ask; if reject -> ask for reason and save.
# -----------------------
st.subheader(_("🚰 Quyết định tưới nước", "🚰 Irrigation Decision"))
is_irrigating = False
irrigation_reason = ""
auto_irrigate = False

# session flags
if "decision_made" not in st.session_state:
    st.session_state["decision_made"] = False
if "decision_date" not in st.session_state:
    st.session_state["decision_date"] = None  # date string when last decision made to avoid repeat same day

# threshold from crop if available
threshold = 60
if plots:
    threshold = required_soil_moisture.get(selected_crop, 60)

# decide if irrigation needed
need_irrigation = sensor_hum < threshold and in_compare_time

if need_irrigation:
    irrigation_reason = _("💧 Độ ẩm thấp hơn mức yêu cầu", "💧 Moisture below required level")
    st.warning(f"💧 { _('Cần tưới nước', 'Irrigation needed') } - { _('Lý do', 'Reason') }: {irrigation_reason}")
    # If user is controller
    if user_type == _("Người điều khiển", "Control Administrator"):
        # if decision already made today for this city -> do not ask again
        today_str = date.today().isoformat()
        if st.session_state["decision_made"] and st.session_state.get("decision_date") == f"{selected_city}_{today_str}":
            st.success(_("Quyết định tưới đã được thực hiện cho hôm nay.", "Irrigation decision already handled today."))
            # find last history entry for this city today to set is_irrigating
            last = next((h for h in reversed(history_data) if h.get("city")==selected_city and h.get("time", "").startswith(date.today().strftime("%Y-%m-%d"))), None)
            is_irrigating = bool(last and last.get("irrigate"))
        else:
            # Show buttons to agree/reject (with 5-minute countdown)
            # initialize timer
            if "wait_start" not in st.session_state:
                st.session_state["wait_start"] = datetime.now(vn_tz).isoformat()
            wait_start = datetime.fromisoformat(st.session_state["wait_start"])
            elapsed = (now - wait_start).total_seconds() / 60.0
            remaining = max(0, 5 - elapsed)
            st.info(f"⏳ { _('Thời gian chờ quyết định', 'Time waiting for decision') }: {remaining:.1f} { _('phút còn lại', 'minutes remaining') }")
            col1, col2 = st.columns(2)
            with col1:
                if st.button(_("✅ Đồng ý bật bơm", "✅ Agree to turn on pump")):
                    st.session_state["decision_made"] = True
                    st.session_state["decision_date"] = f"{selected_city}_{today_str}"
                    is_irrigating = True
                    auto_irrigate = False
                    # record history (Requirement 5)
                    rec = {
                        "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
                        "city": selected_city,
                        "crop": selected_crop if plots else None,
                        "planting_date": planting_date.isoformat() if plots else None,
                        "irrigate": True,
                        "auto": False,
                        "manual_mode": (mode_flag=="manual"),
                        "sensor_temp": sensor_temp,
                        "sensor_hum": sensor_hum,
                        "reason": "Agreed by controller"
                    }
                    history_data.append(rec)
                    save_json(HISTORY_FILE, history_data)
                    st.success(_("💦 ĐÃ BẬT BƠM (theo người điều khiển)", "💦 PUMP TURNED ON (by controller)"))
                    # simulate flow record
                    simulated_flow = round(random.uniform(1.0, 5.0),2)
                    flow_data.append({"time": now.strftime("%Y-%m-%d %H:%M:%S"), "city": selected_city, "flow": simulated_flow})
                    save_json(FLOW_FILE, flow_data)
                # manual trigger (if in manual mode they may also want to trigger)
            with col2:
                if st.button(_("❌ Không đồng ý tưới", "❌ Reject irrigation")):
                    st.session_state["decision_made"] = True
                    st.session_state["decision_date"] = f"{selected_city}_{today_str}"
                    is_irrigating = False
                    # ask for reason
                    reason = st.text_area(_("Vui lòng ghi lý do không tưới:", "Please provide reason for not irrigating:"), "")
                    if st.button(_("💾 Lưu lý do", "💾 Save reason")):
                        rec = {
                            "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
                            "city": selected_city,
                            "crop": selected_crop if plots else None,
                            "planting_date": planting_date.isoformat() if plots else None,
                            "irrigate": False,
                            "auto": False,
                            "manual_mode": (mode_flag=="manual"),
                            "sensor_temp": sensor_temp,
                            "sensor_hum": sensor_hum,
                            "reason": reason or "No reason provided"
                        }
                        history_data.append(rec)
                        save_json(HISTORY_FILE, history_data)
                        st.info(_("🚫 Lệnh tưới bị hủy và lưu lý do.", "🚫 Irrigation cancelled and reason saved."))
            # automatic fallback after 5 minutes if no decision
            if elapsed >= 5 and not st.session_state["decision_made"]:
                # only auto if mode is auto
                if mode_flag == "auto":
                    is_irrigating = True
                    auto_irrigate = True
                    st.success(_("🕔 Sau 5 phút không có quyết định – TỰ ĐỘNG BẬT BƠM", "🕔 No decision after 5 mins – AUTO PUMP ON"))
                    rec = {
                        "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
                        "city": selected_city,
                        "crop": selected_crop if plots else None,
                        "planting_date": planting_date.isoformat() if plots else None,
                        "irrigate": True,
                        "auto": True,
                        "manual_mode": False,
                        "sensor_temp": sensor_temp,
                        "sensor_hum": sensor_hum,
                        "reason": "Auto after timeout"
                    }
                    history_data.append(rec)
                    save_json(HISTORY_FILE, history_data)
                    # simulate flow
                    simulated_flow = round(random.uniform(1.5, 6.0),2)
                    flow_data.append({"time": now.strftime("%Y-%m-%d %H:%M:%S"), "city": selected_city, "flow": simulated_flow})
                    save_json(FLOW_FILE, flow_data)
                else:
                    st.info(_("Chế độ Manual: không tự động bật sau 5 phút.", "Manual mode: will not auto-turn after 5 minutes."))
else:
    st.info(_("✅ Không cần tưới - độ ẩm đủ hoặc ngoài khung giờ", "✅ No irrigation needed - moisture sufficient or outside window"))
    # reset waiting state if not needed
    st.session_state["wait_start"] = None
    # allow manual trigger even if no need (controller)
    if user_type == _("Người điều khiển", "Control Administrator"):
        if st.button(_("🔘 Bật bơm thủ công (Manual)", "🔘 Manual pump ON")):
            # manual pump action: treat as agreed and save history
            rec = {
                "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
                "city": selected_city,
                "crop": selected_crop if plots else None,
                "planting_date": planting_date.isoformat() if plots else None,
                "irrigate": True,
                "auto": False,
                "manual_mode": True,
                "sensor_temp": sensor_temp,
                "sensor_hum": sensor_hum,
                "reason": "Manual trigger"
            }
            history_data.append(rec)
            save_json(HISTORY_FILE, history_data)
            simulated_flow = round(random.uniform(1.0, 4.5),2)
            flow_data.append({"time": now.strftime("%Y-%m-%d %H:%M:%S"), "city": selected_city, "flow": simulated_flow})
            save_json(FLOW_FILE, flow_data)
            st.success(_("💦 Bật bơm thủ công và lưu lịch sử.", "Pump manually turned on and saved to history."))

# If in auto mode and irrigation decided earlier by logic for non-controller (e.g., system auto)
if mode_flag == "auto" and user_type != _("Người điều khiển", "Control Administrator") and need_irrigation:
    # if not already recorded for today, record automatic irrigation
    today_str = date.today().isoformat()
    already_today = any(h for h in history_data if h.get("city")==selected_city and h.get("timestamp","").startswith(today_str) and h.get("auto"))
    if not already_today:
        rec = {
            "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
            "city": selected_city,
            "crop": selected_crop if plots else None,
            "planting_date": planting_date.isoformat() if plots else None,
            "irrigate": True,
            "auto": True,
            "manual_mode": False,
            "sensor_temp": sensor_temp,
            "sensor_hum": sensor_hum,
            "reason": "Auto by system"
        }
        history_data.append(rec)
        save_json(HISTORY_FILE, history_data)
        simulated_flow = round(random.uniform(1.5, 6.0),2)
        flow_data.append({"time": now.strftime("%Y-%m-%d %H:%M:%S"), "city": selected_city, "flow": simulated_flow})
        save_json(FLOW_FILE, flow_data)
        is_irrigating = True
        auto_irrigate = True

# -----------------------
# Data sent to ESP32 (simulated) - Requirement 4 ensures not sending if manual mode (we simulate)
# -----------------------
st.subheader(_("🔁 Dữ liệu gửi về ESP32 (giả lập)", "🔁 Data sent to ESP32 (simulated)"))
esp32_response = {
    "time": now.strftime('%Y-%m-%d %H:%M:%S'),
    "city": selected_city,
    "irrigate": is_irrigating if mode_flag=="auto" else False,  # in manual mode we do not auto-send irrigation commands
    "auto": auto_irrigate,
    "manual_mode": mode_flag=="manual",
    "sensor_temp": sensor_temp,
    "sensor_hum": sensor_hum,
    "reason": irrigation_reason if is_irrigating else "No irrigation"
}
st.code(esp32_response, language='json')

# -----------------------
# History display & saving (Requirement 3 & 5)
# - Save current esp32_response only as telemetry (already saved above when actions occurred)
# - Show history only in comparison window (in_compare_time); otherwise hide
# -----------------------
st.subheader(_("🕘 Lịch sử dữ liệu gửi về ESP32", "🕘 Data History sent to ESP32"))

# Ensure we save any in-memory history changes
save_json(HISTORY_FILE, history_data)
save_json(FLOW_FILE, flow_data)

if in_compare_time:
    if history_data:
        # show last 50 entries for this city
        df_hist = pd.DataFrame(history_data)
        df_hist_city = df_hist[df_hist["city"]==selected_city].sort_values(by="timestamp", ascending=False).head(50)
        if not df_hist_city.empty:
            st.dataframe(df_hist_city)
        else:
            st.info(_("Chưa có dữ liệu lịch sử trong khung giờ so sánh cho khu vực này.", "No history data in comparison window for this location."))
    else:
        st.info(_("Chưa có dữ liệu lịch sử.", "No history data available."))
else:
    st.info(_("Ngoài khung giờ so sánh: lịch sử so sánh không được hiển thị.", "Outside comparison time window: comparison history is not shown."))

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


