import streamlit as st
from datetime import datetime, timedelta, date
import random
from PIL import Image
import requests
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Smart Irrigation WebApp", layout="wide")
st_autorefresh(interval=3600 * 1000, key="refresh")

# --- LOGO ---
col1, col2 = st.columns([1, 6])
with col1:
    try:
        logo = Image.open("logo.png")
        st.image(logo, width=180)
    except:
        st.warning("❌ Không tìm thấy logo.png")
with col2:
    st.markdown("<h3 style='color: #004aad;'>Ho Chi Minh City University of Technology and Education</h3>", unsafe_allow_html=True)
    st.markdown("<h4 style='color: #004aad;'>Faculty of International Training</h4>", unsafe_allow_html=True)

st.markdown("<h2 style='text-align: center;'>🌾 Smart Agricultural Irrigation System 🌾</h2>", unsafe_allow_html=True)

now = datetime.now()
st.markdown(f"**⏰ Thời gian hiện tại:** `{now.strftime('%H:%M:%S - %d/%m/%Y')}`")

# --- PHÂN QUYỀN NGƯỜI DÙNG ---
user_type = st.radio("👤 Bạn là:", ["👨‍🌾 Người điều khiển", "👀 Người giám sát"])
is_controller = user_type == "👨‍🌾 Người điều khiển"

# --- ĐỊA ĐIỂM ---
locations = {
    "TP. Hồ Chí Minh": (10.762622, 106.660172),
    "Hà Nội": (21.028511, 105.804817),
    "Cần Thơ": (10.045161, 105.746857),
    "Đà Nẵng": (16.054407, 108.202167),
    "Bình Dương": (11.3254, 106.4770),
    "Đồng Nai": (10.9453, 106.8133),
}
selected_city = st.selectbox("📍 Chọn địa điểm:", list(locations.keys()))
latitude, longitude = locations[selected_city]

# --- NÔNG SẢN ---
crops = {
    "Ngô": (75, 100),
    "Chuối": (270, 365),
    "Rau cải": (30, 45),
    "Ớt": (70, 90),
}

# CHỈ NGƯỜI ĐIỀU KHIỂN ĐƯỢC CHỌN CÂY VÀ NGÀY TRỒNG
if is_controller:
    selected_crop = st.selectbox("🌱 Chọn loại nông sản:", list(crops.keys()))
    planting_date = st.date_input("📅 Ngày gieo trồng:")
else:
    selected_crop = "Ngô"
    planting_date = date(2025, 7, 1)  # mặc định với người giám sát
    st.info(f"🔒 Đang giám sát cây **{selected_crop}**, trồng từ ngày **{planting_date.strftime('%d/%m/%Y')}**")

# --- TÍNH TOÁN THU HOẠCH ---
min_days, max_days = crops[selected_crop]
harvest_min = planting_date + timedelta(days=min_days)
harvest_max = planting_date + timedelta(days=max_days)
st.success(f"🌾 Dự kiến thu hoạch từ **{harvest_min.strftime('%d/%m/%Y')}** đến **{harvest_max.strftime('%d/%m/%Y')}**")

# --- API THỜI TIẾT ---
weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}&current=temperature_2m,relative_humidity_2m,precipitation,precipitation_probability&timezone=auto"
weather_data = requests.get(weather_url).json()
current_weather = weather_data.get("current", {})

st.subheader("🌦️ Thời tiết hiện tại")
col1, col2, col3 = st.columns(3)
col1.metric("🌡️ Nhiệt độ", f"{current_weather.get('temperature_2m', 'N/A')} °C")
col2.metric("💧 Độ ẩm", f"{current_weather.get('relative_humidity_2m', 'N/A')} %")
col3.metric("🌧️ Mưa", f"{current_weather.get('precipitation', 'N/A')} mm")

# --- GIẢ LẬP CẢM BIẾN ---
st.subheader("🧪 Dữ liệu cảm biến từ ESP32")
sensor_temp = round(random.uniform(25, 37), 1)
sensor_hum = round(random.uniform(50, 95), 1)
sensor_light = round(random.uniform(300, 1000), 1)

st.write(f"🌡️ Nhiệt độ cảm biến: **{sensor_temp} °C**")
st.write(f"💧 Độ ẩm đất cảm biến: **{sensor_hum} %**")
st.write(f"☀️ Cường độ ánh sáng: **{sensor_light} lux**")

# --- SO SÁNH ---
st.subheader("🧠 So sánh dữ liệu cảm biến và thời tiết")
temp_diff = abs(current_weather.get("temperature_2m", 0) - sensor_temp)
hum_diff = abs(current_weather.get("relative_humidity_2m", 0) - sensor_hum)

if temp_diff < 2 and hum_diff < 10:
    st.success("✅ Cảm biến trùng khớp thời tiết.")
else:
    st.warning(f"⚠️ Sai lệch dữ liệu: {temp_diff:.1f}°C & {hum_diff:.1f}%")

# --- GIAI ĐOẠN CÂY ---
st.subheader("📈 Giai đoạn phát triển cây")
days_since = (date.today() - planting_date).days

def giai_doan_cay(crop, days):
    if crop == "Chuối":
        if days <= 14: return "🌱 Mới trồng"
        elif days <= 180: return "🌿 Phát triển"
        elif days <= 330: return "🌼 Ra hoa"
        else: return "🍌 Trước thu hoạch"
    elif crop == "Rau cải":
        return "🌱 Mới trồng" if days <= 25 else "🌿 Trưởng thành"
    elif crop == "Ngô":
        if days <= 25: return "🌱 Mới trồng"
        elif days <= 70: return "🌿 Thụ phấn"
        elif days <= 100: return "🌼 Trái phát triển"
        else: return "🌽 Trước thu hoạch"
    elif crop == "Ớt":
        if days <= 20: return "🌱 Mới trồng"
        elif days <= 500: return "🌼 Ra hoa"
        else: return "🌶️ Trước thu hoạch"

st.info(f"📅 Đã trồng: **{days_since} ngày**\n\n🔍 {giai_doan_cay(selected_crop, days_since)}")

# --- TƯỚI NƯỚC ---
st.subheader("🚰 Quyết định tưới nước")
rain_prob = current_weather.get("precipitation_probability", 0)
is_irrigating = sensor_hum < 60 and rain_prob < 30

if is_irrigating:
    st.success("💦 ĐANG TƯỚI (ESP32 bật bơm)")
else:
    st.info("⛅ Không tưới - độ ẩm đủ hoặc trời sắp mưa.")

# --- KẾT QUẢ JSON ---
st.subheader("🔁 Dữ liệu gửi về ESP32 (giả lập)")
esp32_response = {
    "time": now.strftime('%H:%M:%S'),
    "irrigate": is_irrigating,
    "sensor_temp": sensor_temp,
    "sensor_hum": sensor_hum
}
st.code(esp32_response, language='json')

