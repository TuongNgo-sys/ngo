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

st.set_page_config(page_title="Smart Irrigation WebApp", layout="wide")
st_autorefresh(interval=3600 * 1000, key="refresh")

# --- LANGUAGE SELECT with session_state ---
if "lang" not in st.session_state:
    st.session_state.lang = "English"  # Default

lang = st.sidebar.selectbox(
    "🌐 Language / Ngôn ngữ",
    ["English", "Tiếng Việt"],
    index=0 if st.session_state.lang == "English" else 1,
    key="lang"
)

en = st.session_state.lang == "English"

# --- TRANSLATION FUNCTION ---
def _(en_text, vi_text):
    return en_text if en else vi_text

DATA_FILE = "crop_data.json"

def load_crop_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    else:
        return {}

def save_crop_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f)

crop_data = load_crop_data()

# --- LOGO ---
try:
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 1rem;
        }
        </style>
        """,
        unsafe_allow_html=True
    )
    st.image(Image.open("logo1.png"), width=1200)
except:
    st.warning(_("❌ logo.png not found", "❌ Không tìm thấy logo.png"))

st.markdown(
    f"<h2 style='text-align: center; font-size: 50px;'>🌾 { _('Smart Agricultural Irrigation System', 'Hệ thống tưới tiêu nông nghiệp thông minh') } 🌾</h2>",
    unsafe_allow_html=True
)

# Time zone Vietnam
vn_tz = pytz.timezone("Asia/Ho_Chi_Minh")
now = datetime.now(vn_tz)
st.markdown(
    """
    <style>
    h3 {
        color: #000000 !important;
        font-size: 20px !important;
        font-family: Arial, sans-serif !important;
        font-weight: bold !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)
st.markdown(f"<h3>⏰ { _('Current time', 'Thời gian hiện tại') }: {now.strftime('%d/%m/%Y')}</h3>", unsafe_allow_html=True)

# --- USER ROLE ---
st.sidebar.title(_("🔐 Select User Role", "🔐 Chọn vai trò người dùng"))
user_type = st.sidebar.radio(_("You are:", "Bạn là:"), [_("Control Administrator", "Người điều khiển"), _("Monitoring Officer", "Người giám sát")])

if user_type == _("Control Administrator", "Người điều khiển"):
    password = st.sidebar.text_input(_("🔑 Enter password:", "🔑 Nhập mật khẩu:"), type="password")
    if password != "admin123":
        st.sidebar.error(_("❌ Incorrect password. Access denied.", "❌ Mật khẩu sai. Truy cập bị từ chối."))
        st.stop()
    else:
        st.sidebar.success(_("✅ Authentication successful.", "✅ Xác thực thành công."))

# --- LOCATIONS ---
locations = {
    "TP. Hồ Chí Minh": (10.762622, 106.660172),
    "Hà Nội": (21.028511, 105.804817),
    "Cần Thơ": (10.045161, 105.746857),
    "Đà Nẵng": (16.054407, 108.202167),
    "Bình Dương": (11.3254, 106.4770),
    "Đồng Nai": (10.9453, 106.8133),
}
location_names = {
    "TP. Hồ Chí Minh": _("Ho Chi Minh City", "TP. Hồ Chí Minh"),
    "Hà Nội": _("Hanoi", "Hà Nội"),
    "Cần Thơ": _("Can Tho", "Cần Thơ"),
    "Đà Nẵng": _("Da Nang", "Đà Nẵng"),
    "Bình Dương": _("Binh Duong", "Bình Dương"),
    "Đồng Nai": _("Dong Nai", "Đồng Nai")
}
location_display_names = [location_names[k] for k in locations.keys()]
selected_city_display = st.selectbox(_("📍 Select location:", "📍 Chọn địa điểm:"), location_display_names)
selected_city = next(k for k, v in location_names.items() if v == selected_city_display)
latitude, longitude = locations[selected_city]

# --- CROPS ---
crops = {
    "Ngô": (75, 100), 
    "Chuối": (270, 365),
    "Ớt": (70, 90), 
}
required_soil_moisture = {
    "Ngô": 65,
    "Chuối": 70,
    "Ớt": 65
}
crop_names = {
    "Ngô": _("Corn", "Ngô"),
    "Chuối": _("Banana", "Chuối"),
    "Ớt": _("Chili pepper", "Ớt")
}

if user_type == _("Control Administrator", "Người điều khiển"):
    crop_display_names = [crop_names[k] for k in crops.keys()]
    selected_crop_display = st.selectbox(_("🌱 Select crop type:", "🌱 Chọn loại nông sản:"), crop_display_names)
    selected_crop = next(k for k, v in crop_names.items() if v == selected_crop_display)
    planting_date = st.date_input(_("📅 Planting date:", "📅 Ngày gieo trồng:"))
    if selected_crop in required_soil_moisture:
        st.markdown(f"🌱 **{_('Required soil moisture for', 'Độ ẩm đất cần thiết cho')} {selected_crop}**: **{required_soil_moisture[selected_crop]}%**")
    crop_data[selected_city] = {
        "crop": selected_crop,
        "planting_date": planting_date.isoformat()
    }
    save_crop_data(crop_data)
elif user_type == _("Monitoring Officer", "Người giám sát"):
    if selected_city in crop_data:
        selected_crop = crop_data[selected_city]["crop"]
        planting_date = date.fromisoformat(crop_data[selected_city]["planting_date"])
        st.success(f"📍 { _('Currently growing', 'Đang trồng') }: **{crop_names[selected_crop]}** - **{location_names[selected_city]}** - { _('since', 'từ ngày') } **{planting_date.strftime('%d/%m/%Y')}**")
        if selected_crop in required_soil_moisture:
            st.markdown(f"🌱 **{_('Required soil moisture for', 'Độ ẩm đất cần thiết cho')} {selected_crop}**: **{required_soil_moisture[selected_crop]}%**")
    else:
        st.warning(_("📍 No crop information available in this location.", "📍 Chưa có thông tin gieo trồng tại khu vực này."))
        st.stop()

# --- HARVEST PREDICTION ---
if selected_city in crop_data:
    selected_crop = crop_data[selected_city]["crop"]
    planting_date = date.fromisoformat(crop_data[selected_city]["planting_date"])
    min_days, max_days = crops[selected_crop]
    est_min = planting_date + timedelta(days=min_days)
    est_max = planting_date + timedelta(days=max_days)
    st.info(f"📅 { _('Estimated harvest time for', 'Thời gian thu hoạch dự kiến cho')} **{crop_names[selected_crop]}**: **{est_min.strftime('%d/%m/%Y')} - {est_max.strftime('%d/%m/%Y')}**")

# --- SENSOR DATA SIMULATION ---
st.subheader(_("📊 Real-time Sensor Data", "📊 Dữ liệu cảm biến thời gian thực"))
soil_moisture = random.randint(40, 90)
temperature = random.uniform(25, 37)
humidity = random.uniform(50, 90)

col1, col2, col3 = st.columns(3)
col1.metric(_("🌱 Soil Moisture (%)", "🌱 Độ ẩm đất (%)"), f"{soil_moisture}%")
col2.metric(_("🌡️ Temperature (°C)", "🌡️ Nhiệt độ (°C)"), f"{temperature:.1f}°C")
col3.metric(_("💧 Air Humidity (%)", "💧 Độ ẩm không khí (%)"), f"{humidity:.1f}%")

# --- IRRIGATION CONTROL ---
if user_type == _("Control Administrator", "Người điều khiển"):
    st.subheader(_("💧 Irrigation Control", "💧 Điều khiển tưới tiêu"))
    if st.button(_("Start irrigation", "Bắt đầu tưới")):
        st.success(_("✅ Irrigation system started", "✅ Hệ thống tưới đã bật"))
    if st.button(_("Stop irrigation", "Dừng tưới")):
        st.warning(_("⛔ Irrigation system stopped", "⛔ Hệ thống tưới đã tắt"))

# --- WEATHER WARNING ---
if temperature > 35:
    st.error(_("🔥 High temperature warning!", "🔥 Cảnh báo nhiệt độ cao!"))
elif soil_moisture < required_soil_moisture.get(selected_crop, 60):
    st.warning(_("💧 Soil moisture is below the required level", "💧 Độ ẩm đất thấp hơn mức yêu cầu"))

# --- FOOTER ---
st.markdown("---")
st.caption("📡 API thời tiết: Open-Meteo | Dữ liệu cảm biến: ESP32-WROOM")
st.caption(" Người thực hiện: Ngô Nguyễn Định Tường-Mai Phúc Khang")














