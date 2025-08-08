# web_esp.py
import streamlit as st
from flask import Flask, jsonify
import threading
import requests
from datetime import datetime, timedelta, date
import random
from PIL import Image
from streamlit_autorefresh import st_autorefresh


# ------------------ STREAMLIT APP ------------------

def run_streamlit():
    st.set_page_config(page_title="Smart Irrigation WebApp", layout="wide")

    # Tự động refresh mỗi 10 giây
    st_autorefresh(interval=10 * 1000, key="refresh_time")

    # --- LOGO VÀ TIÊU ĐỀ ---
    col1, col2 = st.columns([1, 6])
    with col1:
        try:
            logo = Image.open("logo.png")
            st.image(logo, width=180)
        except:
            st.warning("❌ Không tìm thấy logo.png")
    with col2:
        st.markdown("<h3 style='text-align: left; color: #004aad; font-family: Times New Roman;'>Ho Chi Minh City University of Technology and Education</h3>", unsafe_allow_html=True)
        st.markdown("<h3 style='text-align: left; color: #004aad; font-family: Times New Roman;'>International Training Institute hoặc Faculty of International Training</h3>", unsafe_allow_html=True)

    st.markdown("<h2 style='text-align: center;'>🌾 Smart Agricultural Irrigation System 🌾</h2>", unsafe_allow_html=True)

    # --- THỜI GIAN THỰC ---
    now = datetime.now()
    st.markdown(f"**⏰ Thời gian hiện tại:** `{now.strftime('%H:%M:%S - %d/%m/%Y')}`")
   
    # --- CHỌN ĐỊA ĐIỂM ---
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

    # --- DANH SÁCH NÔNG SẢN ---
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

    # --- API THỜI TIẾT ---
    weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}&current=temperature_2m,relative_humidity_2m,precipitation,precipitation_probability&timezone=auto"
    weather_data = requests.get(weather_url).json()
    current_weather = weather_data.get("current", {})

    # --- THỜI TIẾT ---
    st.subheader("🌦️ Thời tiết hiện tại tại " + selected_city)
    col1, col2, col3 = st.columns(3)
    col1.metric("🌡️ Nhiệt độ", f"{current_weather.get('temperature_2m', 'N/A')} °C")
    col2.metric("💧 Độ ẩm", f"{current_weather.get('relative_humidity_2m', 'N/A')} %")
    col3.metric("🌧️ Mưa", f"{current_weather.get('precipitation', 'N/A')} mm")

    # --- GIẢ LẬP CẢM BIẾN ---
    st.subheader("🧪 Dữ liệu cảm biến từ ESP32")
    global sensor_temp, sensor_hum, sensor_light
    sensor_temp = round(random.uniform(25, 37), 1)
    sensor_hum = round(random.uniform(50, 95), 1)
    sensor_light = round(random.uniform(300, 1000), 1)

    st.write(f"🌡️ Nhiệt độ cảm biến: **{sensor_temp} °C**")
    st.write(f"💧 Độ ẩm đất cảm biến: **{sensor_hum} %**")
    st.write(f"☀️ Cường độ ánh sáng: **{sensor_light} lux**")

    # --- SO SÁNH AI ---
    st.subheader("🧠 So sánh dữ liệu")
    temp_diff = abs(current_weather.get("temperature_2m", 0) - sensor_temp)
    hum_diff = abs(current_weather.get("relative_humidity_2m", 0) - sensor_hum)

    if temp_diff < 2 and hum_diff < 10:
        st.success("✅ Cảm biến trùng khớp thời tiết.")
    else:
        st.warning(f"⚠️ Sai lệch dữ liệu: {temp_diff:.1f}°C & {hum_diff:.1f}%")

    # --- GIAI ĐOẠN CÂY CHUỐI ---
    days_since_planting = (date.today() - planting_date).days
    if selected_crop == "Chuối":
        def chuoi_stage(days):
            if days <= 14:
                return "🌱 Giai đoạn mới trồng: tưới mỗi ngày nhẹ, tránh úng."
            elif days <= 180:
                return "🌿 Giai đoạn phát triển: tưới 2-3 ngày/lần, trời nắng thì tưới mỗi ngày."
            elif days <= 330:
                return "🌼 Giai đoạn ra hoa nuôi trái: tưới 1-2 ngày/lần để trái ngọt."
            else:
                return "🍌 Trước thu hoạch: giảm nước để chuối ngọt và chắc múi."
        st.info(f"📅 Đã trồng: **{days_since_planting} ngày**\n\n🔍 {chuoi_stage(days_since_planting)}")

     # --- GIAI ĐOẠN CÂY RAU CẢI ---
    days_since_planting = (date.today() - planting_date).days
    if selected_crop == "Rau cải":
        def raucai_stage(days):
            if days <= 25:
                return "🌱 Giai đoạn mới trồng: tưới đều, không để khô."
            else:
                return "🌿 Giai đoạn trưởng thành: giảm dần trước thu hoạch để cải ngon."
        st.info(f"📅 Đã trồng: **{days_since_planting} ngày**\n\n🔍 {raucai_stage(days_since_planting)}")

     # --- GIAI ĐOẠN CÂY NGÔ ---
    days_since_planting = (date.today() - planting_date).days
    if selected_crop == "Ngô":
        def ngo_stage(days):
            if days <= 25:
                return "🌱 Giai đoạn mới trồng: tưới đủ ẩm."
            elif days <= 70:
                return "🌿 Giai đoạn thụ phấn: tưới nhiều, rất quan trọng để tạo hạt."
            elif days <= 100:
                return "🌼 Giai đoạn phát triển trái: duy trì ẩm vừa phải."
            else:
                return " Trước thu hoạch: giảm nước để chuối ngọt và chắc múi."
        st.info(f"📅 Đã trồng: **{days_since_planting} ngày**\n\n🔍 {ngo_stage(days_since_planting)}")

    # --- GIAI ĐOẠN CÂY ỚT ---
    days_since_planting = (date.today() - planting_date).days
    if selected_crop == "Ớt":
        def ot_stage(days):
            if days <= 20:
                return "🌱 Giai đoạn mới trồng: Tưới sương hoặc nhỏ giọt ."
            elif days <= 500:
                return "🌿 Giai đoạn ra hoa: tưới nhiều, cần nước liên tục để quả phát triển."
            else:
                return "🍌 Trước thu hoạch: giảm dần để thu hoạch."
        st.info(f"📅 Đã trồng: **{days_since_planting} ngày**\n\n🔍 {ot_stage(days_since_planting)}")
    # --- QUYẾT ĐỊNH TƯỚI ---
    st.subheader("🚰 Hệ thống tưới")
    global is_irrigating
    rain_prob = current_weather.get("precipitation_probability", 0)

    def should_irrigate(hum, rain):
        return hum < 60 and rain < 30

    is_irrigating = should_irrigate(sensor_hum, rain_prob)
    if is_irrigating:
        st.success("💦 Hệ thống ĐANG TƯỚI (ESP32 bật bơm)")
    else:
        st.info("⛅ Không tưới - độ ẩm đủ hoặc trời sắp mưa.")

    # --- OUTPUT CHO ESP32 ---
    st.subheader("🔁 Kết quả gửi về ESP32")
    global esp32_response
    esp32_response = {
        "time": now.strftime('%H:%M:%S'),
        "irrigate": is_irrigating,
        "sensor_temp": sensor_temp,
        "sensor_hum": sensor_hum
    }
    st.code(esp32_response, language='json')

    st.markdown("---")
    st.caption("📡 API thời tiết: Open-Meteo | Dữ liệu cảm biến: ESP32-WROOM")

# ------------------ FLASK API ------------------

app = Flask(__name__)

@app.route('/api/status', methods=['GET'])
def get_status():
    return jsonify(esp32_response)

def run_flask():
    app.run(port=8000, debug=False)

# ------------------ CHẠY ĐỒNG THỜI ------------------

if __name__ == '__main__':
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()
    run_streamlit()
