# web_esp.py
import streamlit as st
import requests
from datetime import datetime, timedelta, date
import random
from PIL import Image
#from streamlit_autorefresh import st_autorefresh

# ------------------ STREAMLIT APP ------------------
def run_streamlit():
    st.set_page_config(page_title="Smart Irrigation WebApp", layout="wide")
    st_autorefresh(interval=10 * 1000, key="refresh_time")

    col1, col2 = st.columns([1, 6])
    with col1:
        try:
            logo = Image.open("logo.png")
            st.image(logo, width=180)
        except:
            st.warning("❌ Không tìm thấy logo.png")
    with col2:
        st.markdown("<h3 style='text-align: left; color: #004aad;'>Ho Chi Minh City University of Technology and Education</h3>", unsafe_allow_html=True)
        st.markdown("<h3 style='text-align: left; color: #004aad;'>International Training Institute hoặc Faculty of International Training</h3>", unsafe_allow_html=True)

    st.markdown("<h2 style='text-align: center;'>🌾 Smart Agricultural Irrigation System 🌾</h2>", unsafe_allow_html=True)

    now = datetime.now()
    st.markdown(f"**⏰ Thời gian hiện tại:** `{now.strftime('%H:%M:%S - %d/%m/%Y')}`")

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

    crops = {
        "Ngô": (75, 100), 
        "Chuối": (270, 365),
        "Rau cải": (30, 45),
        "Ớt": (70, 90), 
    }
    selected_crop = st.selectbox("🌱 Chọn loại nông sản:", list(crops.keys()))
    planting_date = st.date_input("📅 Chọn ngày gieo trồng:")
    min_days, max_days = crops[selected_crop]
    harvest_min = planting_date + timedelta(days=min_days)
    harvest_max = planting_date + timedelta(days=max_days)
    st.success(f"🌾 Dự kiến thu hoạch từ **{harvest_min.strftime('%d/%m/%Y')}** đến **{harvest_max.strftime('%d/%m/%Y')}**")

    weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}&current=temperature_2m,relative_humidity_2m,precipitation,precipitation_probability&timezone=auto"
    weather_data = requests.get(weather_url).json()
    current_weather = weather_data.get("current", {})

    st.subheader("🌦️ Thời tiết hiện tại tại " + selected_city)
    col1, col2, col3 = st.columns(3)
    col1.metric("🌡️ Nhiệt độ", f"{current_weather.get('temperature_2m', 'N/A')} °C")
    col2.metric("💧 Độ ẩm", f"{current_weather.get('relative_humidity_2m', 'N/A')} %")
    col3.metric("🌧️ Mưa", f"{current_weather.get('precipitation', 'N/A')} mm")

    st.subheader("🧪 Dữ liệu cảm biến từ ESP32")
    sensor_temp = round(random.uniform(25, 37), 1)
    sensor_hum = round(random.uniform(50, 95), 1)
    sensor_light = round(random.uniform(300, 1000), 1)

    st.write(f"🌡️ Nhiệt độ cảm biến: **{sensor_temp} °C**")
    st.write(f"💧 Độ ẩm đất cảm biến: **{sensor_hum} %**")
    st.write(f"☀️ Cường độ ánh sáng: **{sensor_light} lux**")

    st.subheader("🚰 Hệ thống tưới")
    rain_prob = current_weather.get("precipitation_probability", 0)

    def should_irrigate(hum, rain):
        return hum < 60 and rain < 30

    is_irrigating = should_irrigate(sensor_hum, rain_prob)
    if is_irrigating:
        st.success("💦 Hệ thống ĐANG TƯỚI (ESP32 bật bơm)")
    else:
        st.info("⛅ Không tưới - độ ẩm đủ hoặc trời sắp mưa.")

    st.subheader("🔁 Dữ liệu gửi về ESP32 (giả lập)")
    esp32_response = {
        "time": now.strftime('%H:%M:%S'),
        "irrigate": is_irrigating,
        "sensor_temp": sensor_temp,
        "sensor_hum": sensor_hum
    }
    st.code(esp32_response, language='json')

    st.markdown("---")
    st.caption("📡 API thời tiết: Open-Meteo | Dữ liệu cảm biến: ESP32-WROOM")

if __name__ == '__main__':
    run_streamlit()

