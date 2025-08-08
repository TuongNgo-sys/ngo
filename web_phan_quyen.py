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

# --- CHỌN NGÔN NGỮ ---
lang = st.sidebar.selectbox("🌐 Language / Ngôn ngữ", ["Tiếng Việt", "English"])
vi = lang == "Tiếng Việt"

# --- HÀM DỊCH ---
def _(vi_text, en_text):
    return vi_text if vi else en_text

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
    st.warning(_("❌ Không tìm thấy logo.png", "❌ logo.png not found"))

st.markdown(f"<h2 style='text-align: center; font-size: 50px;'>🌾 { _('Hệ thống tưới tiêu nông nghiệp thông minh', 'Smart Agricultural Irrigation System') } 🌾</h2>", unsafe_allow_html=True)

# Thiết lập múi giờ Việt Nam
vn_tz = pytz.timezone("Asia/Ho_Chi_Minh")
now = datetime.now(vn_tz)
#st.markdown(f"<h5>Thời gian hiện tại (VN): {now.strftime('%d/%m/%Y')}</h5>", unsafe_allow_html=True)
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
st.markdown(f"<h3>⏰ { _('Thời gian hiện tại', 'Current time') }:{now.strftime('%d/%m/%Y')}</h3>", unsafe_allow_html=True)

# --- PHÂN QUYỀN ---
st.sidebar.title(_("🔐 Chọn vai trò người dùng", "🔐 Select User Role"))
user_type = st.sidebar.radio(_("Bạn là:", "You are:"), [_("Người giám sát", " Monitoring Officer"), _("Người điều khiển", "Control Administrator")])

if user_type == _("Người điều khiển", "Control Administrator"):
    password = st.sidebar.text_input(_("🔑 Nhập mật khẩu:", "🔑 Enter password:"), type="password")
    if password != "admin123":
        st.sidebar.error(_("❌ Mật khẩu sai. Truy cập bị từ chối.", "❌ Incorrect password. Access denied."))
        st.stop()
    else:
        st.sidebar.success(_("✅ Xác thực thành công.", "✅ Authentication successful."))

# --- ĐỊA ĐIỂM ---
locations = {
    "TP. Hồ Chí Minh": (10.762622, 106.660172),
    "Hà Nội": (21.028511, 105.804817),
    "Cần Thơ": (10.045161, 105.746857),
    "Đà Nẵng": (16.054407, 108.202167),
    "Bình Dương": (11.3254, 106.4770),
    "Đồng Nai": (10.9453, 106.8133),
}
selected_city = st.selectbox(_("📍 Chọn địa điểm:", "📍 Select location:"), list(locations.keys()))
latitude, longitude = locations[selected_city]

# --- NÔNG SẢN ---
crops = {
    "Ngô": (75, 100), 
    "Chuối": (270, 365),
    "Rau cải": (30, 45),
    "Ớt": (70, 90), 
}
# Độ ẩm đất yêu cầu tối thiểu theo loại cây trồng
required_soil_moisture = {
    "Ngô": 65,
    "Chuối": 70,
    "Rau cải": 60,
    "Ớt": 65
}

if user_type == _("Người điều khiển", "Control Administrator"):
    selected_crop = st.selectbox(_("🌱 Chọn loại nông sản:", "🌱 Select crop type:"), list(crops.keys()))
    planting_date = st.date_input(_("📅 Ngày gieo trồng:", "📅 Planting date:"))

    crop_data[selected_city] = {
        "crop": selected_crop,
        "planting_date": planting_date.isoformat()
    }
    save_crop_data(crop_data)

elif user_type == _("Người giám sát", " Monitoring Officer"):
    if selected_city in crop_data:
        selected_crop = crop_data[selected_city]["crop"]
        planting_date = date.fromisoformat(crop_data[selected_city]["planting_date"])
        st.success(f"📍 { _('Đang trồng', 'Currently growing') }: **{selected_crop}** - **{selected_city}** - { _('từ ngày', 'since') } **{planting_date.strftime('%d/%m/%Y')}**")
    else:
        st.warning(_("📍 Chưa có thông tin gieo trồng tại khu vực này.", "📍 No crop information available in this location."))
        st.stop()

# --- DỰ ĐOÁN THU HOẠCH ---
min_days, max_days = crops[selected_crop]
harvest_min = planting_date + timedelta(days=min_days)
harvest_max = planting_date + timedelta(days=max_days)
st.success(f"🌾 { _('Dự kiến thu hoạch từ', 'Expected harvest from') } **{harvest_min.strftime('%d/%m/%Y')}** { _('đến', 'to') } **{harvest_max.strftime('%d/%m/%Y')}**")

# --- API THỜI TIẾT ---
weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}&current=temperature_2m,relative_humidity_2m,precipitation,precipitation_probability&timezone=auto"
weather_data = requests.get(weather_url).json()
current_weather = weather_data.get("current", {})

st.subheader(_("🌦️ Thời tiết hiện tại", "🌦️ Current Weather"))
col1, col2, col3 = st.columns(3)
col1.metric("🌡️ " + _("Nhiệt độ", "Temperature"), f"{current_weather.get('temperature_2m', 'N/A')} °C")
col2.metric("💧 " + _("Độ ẩm", "Humidity"), f"{current_weather.get('relative_humidity_2m', 'N/A')} %")
col3.metric("🌧️ " + _("Mưa", "Rain"), f"{current_weather.get('precipitation', 'N/A')} mm")

# --- GIẢ LẬP CẢM BIẾN ---
st.subheader(_("🧪 Dữ liệu cảm biến từ ESP32", "🧪 Sensor Data from ESP32"))
sensor_temp = round(random.uniform(25, 37), 1)
sensor_hum = round(random.uniform(50, 95), 1)
sensor_light = round(random.uniform(300, 1000), 1)

st.write(f"🌡️ { _('Nhiệt độ cảm biến', 'Sensor temperature') }: **{sensor_temp} °C**")
st.write(f"💧 { _('Độ ẩm đất cảm biến', 'Soil moisture') }: **{sensor_hum} %**")
st.write(f"☀️ { _('Cường độ ánh sáng', 'Light intensity') }: **{sensor_light} lux**")

# --- SO SÁNH ---
st.subheader(_("🧠 So sánh dữ liệu cảm biến và thời tiết (theo khung giờ)", "🧠 Sensor vs Weather Data (by time window)"))
current_hour = now.hour
in_compare_time = (4 <= current_hour < 6) or (13 <= current_hour < 15)

if in_compare_time:
    temp_diff = abs(current_weather.get("temperature_2m", 0) - sensor_temp)
    hum_diff = abs(current_weather.get("relative_humidity_2m", 0) - sensor_hum)

    if temp_diff < 2 and hum_diff < 10:
        st.success(_("✅ Cảm biến trùng khớp thời tiết trong khung giờ cho phép.", "✅ Sensor matches weather within allowed range."))
    else:
        st.warning(f"⚠️ { _('Sai lệch trong khung giờ', 'Deviation detected') }: {temp_diff:.1f}°C & {hum_diff:.1f}%")
else:
    st.info(_("⏱️ Hiện tại không trong khung giờ so sánh (04:00–06:00 hoặc 13:00–15:00).",
              "⏱️ Outside comparison time window (04:00–06:00 or 13:00–15:00)."))

# --- GIAI ĐOẠN CÂY ---
st.subheader(_("📈 Giai đoạn phát triển cây", "📈 Plant Growth Stage"))
days_since = (date.today() - planting_date).days

def giai_doan_cay(crop, days):
    if crop == "Chuối":
        if days <= 14: return _("🌱 Mới trồng", "🌱 Newly planted")
        elif days <= 180: return _("🌿 Phát triển", "🌿 Growing")
        elif days <= 330: return _("🌼 Ra hoa", "🌼 Flowering")
        else: return _("🍌 Trước thu hoạch", "🍌 Pre-harvest")
    elif crop == "Rau cải":
        return _("🌱 Mới trồng", "🌱 Newly planted") if days <= 25 else _("🌿 Trưởng thành", "🌿 Mature")
    elif crop == "Ngô":
        if days <= 25: return _("🌱 Mới trồng", "🌱 Newly planted")
        elif days <= 70: return _("🌿 Thụ phấn", "🌿 Pollination")
        elif days <= 100: return _("🌼 Trái phát triển", "🌼 Kernel growth")
        else: return _("🌽 Trước thu hoạch", "🌽 Pre-harvest")
    elif crop == "Ớt":
        if days <= 20: return _("🌱 Mới trồng", "🌱 Newly planted")
        elif days <= 500: return _("🌼 Ra hoa", "🌼 Flowering")
        else: return _("🌶️ Trước thu hoạch", "🌶️ Pre-harvest")

st.info(f"📅 { _('Đã trồng', 'Planted for') }: **{days_since} { _('ngày', 'days') }**\n\n🔍 {giai_doan_cay(selected_crop, days_since)}")

# --- TƯỚI NƯỚC ---
st.subheader(_("🚰 Quyết định tưới nước", "🚰 Irrigation Decision"))

is_irrigating = False
irrigation_reason = ""

if in_compare_time:
    threshold = required_soil_moisture.get(selected_crop, 60)
    if sensor_hum < threshold:
        is_irrigating = True
        irrigation_reason = _("💧 Độ ẩm thấp hơn mức yêu cầu", "💧 Moisture below required level")
        st.success(f"💦 { _('ĐANG TƯỚI (ESP32 bật bơm)', 'IRRIGATING (ESP32 pump ON)') }")
        st.info(f"📉 { _('Lý do', 'Reason') }: {irrigation_reason} ({sensor_hum:.1f}% < {threshold}%)")
    else:
        st.info(f"✅ { _('Không tưới - độ ẩm đủ', 'No irrigation - soil moisture sufficient') } ({sensor_hum:.1f}% ≥ {threshold}%)")
else:
    st.info(_("⏱️ Không trong khung giờ tưới (04:00–06:00 hoặc 13:00–15:00)", "⏱️ Not in irrigation time window (04:00–06:00 or 13:00–15:00)"))

# --- KẾT QUẢ JSON ---
st.subheader(_("🔁 Dữ liệu gửi về ESP32 (giả lập)", "🔁 Data sent to ESP32 (simulated)"))
esp32_response = {
    "time": now.strftime('%H:%M:%S'),
    "irrigate": is_irrigating,
    "sensor_temp": sensor_temp,
    "sensor_hum": sensor_hum
}
st.code(esp32_response, language='json')
# --- LỊCH SỬ GỬI DỮ LIỆU ---
st.subheader(_("🕘 Lịch sử dữ liệu gửi về ESP32", "🕘 Data History sent to ESP32"))

HISTORY_FILE = "history_irrigation.json"

# Load lịch sử
if os.path.exists(HISTORY_FILE):
    with open(HISTORY_FILE, "r") as f:
        history_data = json.load(f)
else:
    history_data = []

# Lưu bản ghi hiện tại
history_data.append(esp32_response)
with open(HISTORY_FILE, "w") as f:
    json.dump(history_data, f, ensure_ascii=False, indent=2)

# Hiển thị bảng lịch sử chỉ trong khung giờ so sánh
import pandas as pd

def in_time_window(t):
    try:
        hour = int(t.split(":")[0])
        return (4 <= hour < 6) or (13 <= hour < 15)
    except:
        return False

filtered_data = list(filter(lambda d: in_time_window(d["time"]), history_data))

if filtered_data:
    df_history = pd.DataFrame(filtered_data)
    df_history = df_history.sort_values(by="time", ascending=False).head(10)
    st.dataframe(df_history)
else:
    st.info(_("Chưa có dữ liệu lịch sử trong khung giờ so sánh.", "No history data available in comparison time window."))

# --- GHI CHÚ ---
st.markdown("---")
st.caption("📡 API thời tiết: Open-Meteo | Dữ liệu cảm biến: ESP32-WROOM")
st.caption(" Người thực hiện: Ngô Nguyễn Định Tường-Mai Phúc Khang")












































