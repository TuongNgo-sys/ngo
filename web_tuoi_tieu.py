# web_esp.py
import streamlit as st
from datetime import datetime, timedelta, date, time
import json
import os
import pytz
import pandas as pd
import threading
import random
from PIL import Image
import requests
import paho.mqtt.client as mqtt
import matplotlib.pyplot as plt  # plotting
#from streamlit_autorefresh import st_autorefresh
# -----------------------
# Config & helpers
# -----------------------
st.set_page_config(page_title="Smart Irrigation WebApp", layout="wide")

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

# Timezone (moved up so helper can use)
vn_tz = pytz.timezone("Asia/Ho_Chi_Minh")

# -----------------------
# Helper: giữ dữ liệu trong vòng N ngày (mặc định 365)
# -----------------------
def filter_recent_list(lst, time_key, days=365):
    """
    lst: list of dicts
    time_key: key string containing ISO timestamp (e.g. 'timestamp' or 'time' or 'start_time')
    returns filtered list containing only records within last `days` days
    """
    try:
        cutoff = datetime.now(vn_tz) - timedelta(days=days)
    except Exception:
        cutoff = datetime.utcnow() - timedelta(days=days)
    out = []
    for item in lst:
        ts = item.get(time_key)
        if not ts:
            # try other keys like start_time
            ts = item.get("start_time") or item.get("time") or item.get("timestamp")
            if not ts:
                continue
        try:
            dt = datetime.fromisoformat(ts)
        except:
            try:
                dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")
            except:
                # ignore unparsable
                continue
        # ensure timezone-aware comparison
        if dt.tzinfo is None:
            dt = vn_tz.localize(dt)
        if dt >= cutoff:
            out.append(item)
    return out

# -----------------------
# Hàm thêm record lưu lượng vào flow_data
# -----------------------
def add_flow_record(flow_val, location=""):
    now_iso = datetime.now(vn_tz).isoformat()
    new_record = {
        "time": now_iso,
        "flow": flow_val,
        "location": location,
    }
    flow = load_json(FLOW_FILE, [])
    flow.append(new_record)
    save_json(FLOW_FILE, flow)

# Hàm thêm record cảm biến vào history
def add_history_record(sensor_hum, sensor_temp, location=""):
    now_iso = datetime.now(vn_tz).isoformat()
    new_record = {
        "timestamp": now_iso,
        "sensor_hum": sensor_hum,
        "sensor_temp": sensor_temp,
        "location": location,
    }
    history = load_json(HISTORY_FILE, [])
    history.append(new_record)
    save_json(HISTORY_FILE, history)

# Hàm chuyển list dict lịch sử thành DataFrame và sắp xếp theo thời gian
def to_df(lst):
    if not lst:
        return pd.DataFrame()
    df = pd.DataFrame(lst)
    time_col = "timestamp" if "timestamp" in df.columns else ("time" if "time" in df.columns else None)
    if time_col:
        df[time_col] = pd.to_datetime(df[time_col], errors='coerce')
        df = df.dropna(subset=[time_col])
        df = df.sort_values(by=time_col)
        df = df.reset_index(drop=True)
    return df

# -----------------------
# Load persistent data (và lọc lịch sử chỉ 1 năm gần nhất)
# -----------------------
crop_data = load_json(DATA_FILE, {})
# load full then filter history & flow to recent 365 days
_raw_history = load_json(HISTORY_FILE, [])
_raw_flow = load_json(FLOW_FILE, [])
# filter
history_data = filter_recent_list(_raw_history, "timestamp", days=365)
flow_data = filter_recent_list(_raw_flow, "time", days=365)
# save trimmed back (so file size won't keep growing indefinitely)
save_json(HISTORY_FILE, history_data)
save_json(FLOW_FILE, flow_data)

# config default
config = load_json(CONFIG_FILE, {"watering_schedule": "06:00-08:00", "mode": "auto"})

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

now = datetime.now(vn_tz)
st.markdown(f"<h2 style='text-align: center; font-size: 50px;'>🌾 { _('Hệ thống tưới tiêu nông nghiệp thông minh', 'Smart Agricultural Irrigation System') } 🌾</h2>", unsafe_allow_html=True)
st.markdown(f"<h3>⏰ { _('Thời gian hiện tại', 'Current time') }: {now.strftime('%d/%m/%Y %H:%M:%S')}</h3>", unsafe_allow_html=True)

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
# Crop management
# -----------------------
st.header(_("🌱 Quản lý cây trồng", "🌱 Crop Management"))
mode_flag = config.get("mode", "auto")

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

# --- NEW: Controller - choose sub-plot and view planting history (1 year)
if user_type == _("Người điều khiển", "Control Administrator"):
    st.subheader(_("📚 Lịch sử cây đã trồng (1 năm)", "📚 Planting history (1 year)"))
    plots_all = crop_data.get(selected_city, {}).get("plots", [])
    if plots_all:
        rows_hist = []
        cutoff_dt = date.today() - timedelta(days=365)
        for idx, p in enumerate(plots_all):
            crop_k = p.get("crop")
            pd_iso = p.get("planting_date")
            try:
                pd_date = date.fromisoformat(pd_iso)
            except:
                pd_date = date.today()
            if pd_date >= cutoff_dt:
                rows_hist.append({
                    "plot_index": idx,
                    "crop": crop_names.get(crop_k, crop_k),
                    "planting_date": pd_date.strftime("%d/%m/%Y")
                })
        if rows_hist:
            df_hist_plants = pd.DataFrame(rows_hist)
            st.dataframe(df_hist_plants)
        else:
            st.info(_("Không có cây được trồng trong vòng 1 năm tại khu vực này.", "No plantings within last 1 year in this location."))
    else:
        st.info(_("Chưa có vùng trồng nào trong khu vực này.", "No plots in this location yet."))

# --- NEW: Controller - choose which plot to control pump for
if user_type == _("Người điều khiển", "Control Administrator"):
    st.subheader(_("🚰 Điều khiển bơm cho từng khu vực con (plot)", "🚰 Pump control per plot"))
    plots_for_control = crop_data.get(selected_city, {}).get("plots", [])
    if not plots_for_control:
        st.info(_("Chưa có khu vực con (plot) để điều khiển. Vui lòng thêm vùng trồng.", "No sub-plots to control. Please add plantings."))
    else:
        plot_labels = []
        for i, p in enumerate(plots_for_control):
            crop_k = p.get("crop")
            pd_iso = p.get("planting_date", "")
            label = f"Plot {i} - {crop_names.get(crop_k, crop_k)} - {pd_iso}"
            plot_labels.append(label)
        selected_plot_label = st.selectbox(_("Chọn khu vực con để điều khiển:", "Select plot to control:"), plot_labels)
        selected_plot_index = plot_labels.index(selected_plot_label)
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button(_("🔛 Bật bơm cho khu vực đã chọn", "🔛 Turn ON pump for selected plot")):
                history_irrigation = load_json(HISTORY_FILE, [])
                new_irrigation = {
                    "location": selected_city,
                    "plot_index": selected_plot_index,
                    "crop": plots_for_control[selected_plot_index].get("crop"),
                    "start_time": datetime.now(vn_tz).isoformat(),
                    "end_time": None,
                }
                history_irrigation.append(new_irrigation)
                save_json(HISTORY_FILE, history_irrigation)
                st.success(_("✅ Đã bật bơm cho khu vực.", "✅ Pump turned ON for selected plot."))
        with col_b:
            if st.button(_("⏹ Dừng bơm cho khu vực đã chọn", "⏹ Stop pump for selected plot")):
                history_irrigation = load_json(HISTORY_FILE, [])
                for i in reversed(range(len(history_irrigation))):
                    rec = history_irrigation[i]
                    if rec.get("location") == selected_city and rec.get("plot_index") == selected_plot_index and rec.get("end_time") is None:
                        history_irrigation[i]["end_time"] = datetime.now(vn_tz).isoformat()
                        save_json(HISTORY_FILE, history_irrigation)
                        st.success(_("🚰 Đã dừng bơm cho khu vực.", "🚰 Pump stopped for selected plot."))
                        break
                else:
                    st.info(_("Không tìm thấy phiên tưới đang mở cho khu vực này.", "No open irrigation session found for this plot."))

# -----------------------
# Người giám sát (Monitoring Officer)
# -----------------------
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

    st.subheader(_("📜 Lịch sử tưới nước", "📜 Irrigation History"))
    irrigation_hist = load_json(HISTORY_FILE, [])
    filtered_irrigation = [r for r in irrigation_hist if r.get("location") == selected_city]
    if filtered_irrigation:
        df_irrig = pd.DataFrame(filtered_irrigation)
        if "start_time" in df_irrig.columns:
            df_irrig["start_time"] = pd.to_datetime(df_irrig["start_time"])
        if "end_time" in df_irrig.columns:
            df_irrig["end_time"] = pd.to_datetime(df_irrig["end_time"])
        st.dataframe(df_irrig.sort_values(by="start_time", ascending=False))
    else:
        st.info(_("Chưa có lịch sử tưới cho khu vực này.", "No irrigation history for this location."))

    st.header(_("📊 Biểu đồ lịch sử cảm biến", "📊 Sensor History Charts"))
    history_data = load_json(HISTORY_FILE, [])
    flow_data = load_json(FLOW_FILE, [])
    filtered_hist = [h for h in history_data if h.get("location") == selected_city]
    filtered_flow = [f for f in flow_data if f.get("location") == selected_city]
    df_hist_all = pd.DataFrame(filtered_hist)
    df_flow_all = pd.DataFrame(filtered_flow)

    if not df_hist_all.empty and 'timestamp' in df_hist_all.columns:
        df_hist_all['timestamp'] = pd.to_datetime(df_hist_all['timestamp'], errors='coerce')
        fig, ax1 = plt.subplots(figsize=(12, 5))
        ax1.plot(df_hist_all['timestamp'], df_hist_all['sensor_hum'], 'b-', label=_("Độ ẩm đất", "Soil Humidity"))
        ax1.set_xlabel(_("Thời gian", "Time"))
        ax1.set_ylabel(_("Độ ẩm đất (%)", "Soil Humidity (%)"), color='b')
        ax1.tick_params(axis='y', labelcolor='b')
        ax2 = ax1.twinx()
        if 'sensor_temp' in df_hist_all.columns:
            ax2.plot(df_hist_all['timestamp'], df_hist_all['sensor_temp'], 'r-', label=_("Nhiệt độ", "Temperature"))
            ax2.set_ylabel(_("Nhiệt độ (°C)", "Temperature (°C)"), color='r')
            ax2.tick_params(axis='y', labelcolor='r')
        ax1.legend(loc='upper left')
        ax2.legend(loc='upper right')
        plt.title(_("Lịch sử độ ẩm đất và nhiệt độ", "Soil Humidity and Temperature History"))
        plt.xticks(rotation=45)
        plt.tight_layout()
        st.pyplot(fig)
    else:
        st.info(_("Chưa có dữ liệu cảm biến cho khu vực này.", "No sensor data for this location."))

    if not df_flow_all.empty and 'time' in df_flow_all.columns:
        df_flow_all['time'] = pd.to_datetime(df_flow_all['time'], errors='coerce')
        fig2, ax3 = plt.subplots(figsize=(12, 3))
        ax3.plot(df_flow_all['time'], df_flow_all['flow'], 'g-', label=_("Lưu lượng nước (L/min)", "Water Flow (L/min)"))
        ax3.set_xlabel(_("Thời gian", "Time"))
        ax3.set_ylabel(_("Lưu lượng nước (L/min)", "Water Flow (L/min)"), color='g')
        ax3.tick_params(axis='y', labelcolor='g')
        ax3.legend()
        plt.title(_("Lịch sử lưu lượng nước", "Water Flow History"))
        plt.xticks(rotation=45)
        plt.tight_layout()
        st.pyplot(fig2)
    else:
        st.info(_("Chưa có dữ liệu lưu lượng nước cho khu vực này.", "No water flow data for this location."))

# -----------------------
# Weather (Open-Meteo) + charts + auto-refresh 30 minutes
# -----------------------
# Auto refresh UI every 30 minutes
st_autorefresh(interval=30*60*1000, key="weather_refresh")

st.header(_("🌦 Dự báo thời tiết & so sánh mưa - tưới", "🌦 Weather Forecast & Rain-Irrigation Comparison"))

def fetch_open_meteo(lat, lon):
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&hourly=precipitation"
        "&daily=precipitation_sum"
        "&timezone=auto"
    )
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json()

try:
    wdata = fetch_open_meteo(latitude, longitude)

    # hourly
    hr_times = pd.to_datetime(wdata.get("hourly", {}).get("time", []))
    hr_prec = wdata.get("hourly", {}).get("precipitation", [])
    df_hr = pd.DataFrame({"time": hr_times, "rain_mm": hr_prec}).set_index("time")

    # daily
    dy_dates = pd.to_datetime(wdata.get("daily", {}).get("time", []))
    dy_sum = wdata.get("daily", {}).get("precipitation_sum", [])
    df_dy = pd.DataFrame({"date": dy_dates.date, "rain_mm": dy_sum}).set_index("date")

    # total 48h
    total_48h = float(df_hr["rain_mm"].iloc[:48].sum()) if not df_hr.empty else 0.0

    st.markdown(f"**{_('Tổng lượng mưa trong 48 giờ tới:', 'Total rain next 48h:')} {total_48h:.1f} mm**")

    # Plot hourly rain (line)
    if not df_hr.empty:
        fig_h, axh = plt.subplots(figsize=(12,4))
        axh.plot(df_hr.index, df_hr["rain_mm"], marker='o', linestyle='-')
        axh.set_title(_("Mưa theo giờ (48h)", "Hourly Rain (48h)"))
        axh.set_xlabel(_("Thời gian", "Time")); axh.set_ylabel(_("Mưa (mm)", "Rain (mm)"))
        plt.xticks(rotation=45); plt.tight_layout()
        st.pyplot(fig_h)
    else:
        st.info(_("Không có dữ liệu mưa theo giờ.", "No hourly rain data."))

    # Plot daily rain (bar)
    if not df_dy.empty:
        fig_d, axd = plt.subplots(figsize=(10,4))
        axd.bar([d.strftime("%d/%m") for d in df_dy.index], df_dy["rain_mm"])
        axd.set_title(_("Mưa theo ngày", "Daily Rain Total"))
        axd.set_xlabel(_("Ngày", "Date")); axd.set_ylabel(_("Mưa tổng (mm/ngày)", "Precipitation (mm/day)"))
        plt.xticks(rotation=45); plt.tight_layout()
        st.pyplot(fig_d)
    else:
        st.info(_("Không có dữ liệu mưa theo ngày.", "No daily rain data."))

    # ==== Compare Rain vs Irrigation ====
    # Build daily irrigation volume estimate:
    # Approach:
    # - For each irrigation session in HISTORY_FILE (start_time,end_time), compute duration minutes.
    # - Estimate avg flow (L/min) for that location using flow_data recent values; if not available, use fallback 0.
    # - Volume_liters = duration_minutes * avg_flow -> sum per day.
    hist = load_json(HISTORY_FILE, [])
    flow = load_json(FLOW_FILE, [])

    irrig_df = pd.DataFrame(hist)
    flow_df = pd.DataFrame(flow)

    daily_irrig_liters = pd.Series(dtype=float)

    if not irrig_df.empty and "start_time" in irrig_df.columns:
        # compute avg flow per location (overall, fallback)
        avg_flow_by_loc = {}
        if not flow_df.empty and "time" in flow_df.columns:
            flow_df["time"] = pd.to_datetime(flow_df["time"], errors='coerce')
            grouped = flow_df.groupby("location")["flow"].mean()
            avg_flow_by_loc = grouped.to_dict()

        # compute per session durations and convert to liters
        irrig_df["start_time_parsed"] = pd.to_datetime(irrig_df["start_time"], errors='coerce')
        irrig_df["end_time_parsed"] = pd.to_datetime(irrig_df["end_time"], errors='coerce')
        # for open sessions without end_time, use now
        irrig_df["end_time_parsed"] = irrig_df["end_time_parsed"].fillna(datetime.now(vn_tz))
        irrig_df["duration_min"] = (irrig_df["end_time_parsed"] - irrig_df["start_time_parsed"]).dt.total_seconds().div(60).clip(lower=0)
        # estimate liters per session
        def estimate_session_liters(row):
            loc = row.get("location")
            avgf = avg_flow_by_loc.get(loc, None)
            if avgf is None or pd.isna(avgf):
                # fallback heuristics: assume 5 L/min if no data (you can change)
                avgf = 5.0
            return float(row.get("duration_min", 0.0)) * float(avgf)
        irrig_df["liters"] = irrig_df.apply(estimate_session_liters, axis=1)
        irrig_df["date"] = irrig_df["start_time_parsed"].dt.date
        daily_irrig_liters = irrig_df.groupby("date")["liters"].sum()

    # Make comparison dataframe covering days in df_dy index (daily forecast)
    cmp_idx = sorted(set(df_dy.index.tolist() + daily_irrig_liters.index.tolist()))
    cmp_df = pd.DataFrame(index=cmp_idx)
    if not df_dy.empty:
        cmp_df["rain_mm"] = df_dy["rain_mm"]
    else:
        cmp_df["rain_mm"] = 0.0
    if not daily_irrig_liters.empty:
        cmp_df["irrig_liters"] = daily_irrig_liters
    else:
        cmp_df["irrig_liters"] = 0.0
    cmp_df = cmp_df.fillna(0.0)

    if not cmp_df.empty:
        fig_c, axc = plt.subplots(figsize=(12,4))
        axc.bar([d.strftime("%d/%m") for d in cmp_df.index], cmp_df["rain_mm"], label=_("Mưa (mm)", "Rain (mm)"))
        axc.set_ylabel(_("Mưa (mm)", "Rain (mm)"))
        axc.set_xlabel(_("Ngày", "Date"))
        axc_twin = axc.twinx()
        axc_twin.plot([d.strftime("%d/%m") for d in cmp_df.index], cmp_df["irrig_liters"], color='orange', marker='o', label=_("Tổng tưới (L)", "Total irrigation (L)"))
        axc_twin.set_ylabel(_("Tổng tưới (L)", "Total irrigation (L)"))
        axc.set_title(_("So sánh mưa (mm) và tổng tưới (L) theo ngày", "Rain (mm) vs irrigation (L) per day"))
        axc.legend(loc='upper left')
        axc_twin.legend(loc='upper right')
        plt.xticks(rotation=45); plt.tight_layout()
        st.pyplot(fig_c)
    else:
        st.info(_("Không có dữ liệu để so sánh mưa và tưới.", "No data to compare rain and irrigation."))

    # Alert: nếu mưa hôm nay >= threshold -> cảnh báo
    rain_threshold_mm = st.sidebar.number_input(_("Ngưỡng mưa để hủy tưới (mm)", "Rain threshold to skip irrigation (mm)"), value=10.0, step=1.0)
    today_dt = date.today()
    rain_today = float(cmp_df.reindex([today_dt])["rain_mm"]) if today_dt in cmp_df.index else 0.0
    if rain_today >= rain_threshold_mm:
        st.warning(_("⚠️ CẢNH BÁO: Hôm nay đã mưa đủ ({:.1f} mm). Không cần tưới.".format(rain_today),
                     "⚠️ ALERT: Enough rain today ({:.1f} mm). No irrigation needed.".format(rain_today)))
    else:
        st.info(_("🌤 Mưa hôm nay: {:.1f} mm — vẫn có thể cần tưới nếu độ ẩm thấp.".format(rain_today),
                  "🌤 Rain today: {:.1f} mm — irrigation may still be needed if soil moisture is low.".format(rain_today)))

except Exception as e:
    st.error(_("Lỗi khi lấy dữ liệu thời tiết:", "Error fetching weather data:") + f" {e}")

# -----------------------
# Mode and Watering Schedule (shared config.json)
# -----------------------
st.header(_("⚙️ Cấu hình chung hệ thống", "⚙️ System General Configuration"))

if user_type == _("Người điều khiển", "Control Administrator"):
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(_("### ⏲️ Khung giờ tưới nước", "### ⏲️ Watering time window"))
        start_time = st.time_input(
            _("Giờ bắt đầu", "Start time"),
            value=datetime.strptime(config["watering_schedule"].split("-")[0], "%H:%M").time(),
        )
        end_time = st.time_input(
            _("Giờ kết thúc", "End time"),
            value=datetime.strptime(config["watering_schedule"].split("-")[1], "%H:%M").time(),
        )
    with col2:
        st.markdown(_("### 🔄 Chọn chế độ", "### 🔄 Select operation mode"))
        main_mode = st.radio(
            _("Chọn chế độ điều khiển", "Select control mode"),
            [_("Tự động", "Automatic"), _("Thủ công", "Manual")],
            index=0 if config.get("mode", "auto") == "auto" else 1,
        )

        manual_control_type = None
        if main_mode == _("Thủ công", "Manual"):
            manual_control_type = st.radio(
                _("Chọn phương thức thủ công", "Select manual control type"),
                [_("Thủ công trên app", "Manual on app"), _("Thủ công ở tủ điện", "Manual on cabinet")],
            )

    if st.button(_("💾 Lưu cấu hình", "💾 Save configuration")):
        config["watering_schedule"] = f"{start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')}"
        if main_mode == _("Tự động", "Automatic"):
            config["mode"] = "auto"
            config.pop("manual_control_type", None)
        else:
            config["mode"] = "manual"
            config["manual_control_type"] = manual_control_type
        save_json(CONFIG_FILE, config)
        st.success(_("Đã lưu cấu hình.", "Configuration saved."))

else:
    st.markdown(
        _("⏲️ Khung giờ tưới nước hiện tại:", "⏲️ Current watering time window:") + f" **{config['watering_schedule']}**"
    )
    mode_display = _("Tự động", "Automatic") if config.get("mode", "auto") == "auto" else _("Thủ công", "Manual")
    st.markdown(_("🔄 Chế độ hoạt động hiện tại:", "🔄 Current operation mode:") + f" **{mode_display}**")
    if config.get("mode") == "manual":
        manual_type_display = config.get("manual_control_type", "")
        if manual_type_display == _("Thủ công trên app", "Manual on app") or manual_type_display == "Manual on app":
            st.markdown(_("⚙️ Phương thức thủ công: Thủ công trên app", "⚙️ Manual method: Manual on app"))
        elif manual_type_display == _("Thủ công ở tủ điện", "Thủ công ở tủ điện") or manual_type_display == "Manual on cabinet":
            st.markdown(_("⚙️ Phương thức thủ công: Thủ công ở tủ điện", "⚙️ Manual method: Manual on cabinet"))

# Kiểm tra thời gian trong khung tưới
def is_in_watering_time():
    now_time = datetime.now(vn_tz).time()
    start_str, end_str = config["watering_schedule"].split("-")
    start_t = datetime.strptime(start_str, "%H:%M").time()
    end_t = datetime.strptime(end_str, "%H:%M").time()
    if start_t <= now_time <= end_t:
        return True
    return False

# -----------------------
# MQTT Client for receiving data from ESP32-WROOM
# -----------------------
mqtt_broker = "broker.hivemq.com"  # Thay broker phù hợp
mqtt_port = 1883
mqtt_topic_humidity = "esp32/soil_moisture"
mqtt_topic_flow = "esp32/water_flow"

# Global data containers for live update
live_soil_moisture = []
live_water_flow = []

def on_connect(client, userdata, flags, rc):
    print(f"Connected with result code {rc}")
    client.subscribe(mqtt_topic_humidity)
    client.subscribe(mqtt_topic_flow)

def on_message(client, userdata, msg):
    topic = msg.topic
    payload = msg.payload.decode()
    now_iso = datetime.now(vn_tz).isoformat()
    try:
        val = float(payload)
    except:
        val = None
    if val is not None:
        if topic == mqtt_topic_humidity:
            live_soil_moisture.append({"timestamp": now_iso, "sensor_hum": val, "location": selected_city})
            hist = load_json(HISTORY_FILE, [])
            hist.append({"timestamp": now_iso, "sensor_hum": val, "location": selected_city})
            hist_trimmed = filter_recent_list(hist, "timestamp", days=365)
            save_json(HISTORY_FILE, hist_trimmed)
        elif topic == mqtt_topic_flow:
            live_water_flow.append({"time": now_iso, "flow": val, "location": selected_city})
            flow = load_json(FLOW_FILE, [])
            flow.append({"time": now_iso, "flow": val, "location": selected_city})
            flow_trimmed = filter_recent_list(flow, "time", days=365)
            save_json(FLOW_FILE, flow_trimmed)

def mqtt_thread():
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(mqtt_broker, mqtt_port, 60)
    client.loop_forever()

threading.Thread(target=mqtt_thread, daemon=True).start()

# -----------------------
# Hiển thị biểu đồ dữ liệu mới nhất
# -----------------------
st.header(_("📊 Biểu đồ dữ liệu cảm biến hiện tại", "📊 Current Sensor Data Charts"))
df_soil_live = to_df(live_soil_moisture)
df_flow_live = to_df(live_water_flow)

col1, col2 = st.columns(2)
with col1:
    st.markdown(_("### Độ ẩm đất (Sensor Humidity)", "### Soil Moisture"))
    if not df_soil_live.empty:
        st.line_chart(df_soil_live["sensor_hum"])
    else:
        st.info(_("Chưa có dữ liệu độ ẩm đất nhận từ ESP32.", "No soil moisture data received from ESP32."))

with col2:
    st.markdown(_("### Lưu lượng nước (Water Flow)", "### Water Flow"))
    if not df_flow_live.empty:
        st.line_chart(df_flow_live["flow"])
    else:
        st.info(_("Chưa có dữ liệu lưu lượng nước nhận từ ESP32.", "No water flow data received from ESP32."))

# -----------------------
# Phần tưới nước tự động hoặc thủ công (dành cho người điều khiển)
# -----------------------
if user_type == _("Người điều khiển", "Control Administrator"):
    st.header(_("🚿 Điều khiển hệ thống tưới", "🚿 Irrigation Control"))
    water_on = st.checkbox(_("Bật bơm tưới", "Pump ON"))
    if water_on:
        st.success(_("Bơm đang hoạt động...", "Pump is ON..."))
    else:
        st.info(_("Bơm đang tắt", "Pump is OFF"))

import time

if user_type == _("Người điều khiển", "Control Administrator"):
    st.header(_("🚿 Điều khiển hệ thống tưới", "🚿 Irrigation Control"))

    plots = crop_data.get(selected_city, {}).get("plots", [])
    if len(plots) == 0:
        st.warning(_("❗ Khu vực chưa có cây trồng. Vui lòng cập nhật trước khi tưới.", "❗ No crops found in location. Please update before irrigation."))
    else:
        crop_info = plots[0]
        crop_key = crop_info["crop"]
        thresh_moisture = required_soil_moisture.get(crop_key, 65)

        hist_crop = [h for h in history_data if h.get("location") == selected_city]
        if hist_crop:
            latest_data = sorted(hist_crop, key=lambda x: x["timestamp"], reverse=True)[0]
            current_moisture = latest_data.get("sensor_hum", None)
        else:
            current_moisture = None

        st.markdown(f"**{_('Cây trồng hiện tại', 'Current crop')}:** {crop_names[crop_key]}")
        st.markdown(f"**{_('Độ ẩm đất hiện tại', 'Current soil moisture')}:** {current_moisture if current_moisture is not None else _('Chưa có dữ liệu', 'No data yet')} %")
        st.markdown(f"**{_('Ngưỡng độ ẩm tối thiểu để không tưới', 'Minimum moisture threshold')}:** {thresh_moisture} %")

        if is_in_watering_time():
            st.info(_("⏰ Hiện đang trong khung giờ tưới.", "⏰ Currently in watering time window."))
            if config.get("mode", "auto") == "auto":
                if current_moisture is not None and current_moisture < thresh_moisture:
                    st.success(_("✅ Độ ẩm thấp, bắt đầu tưới tự động.", "✅ Moisture low, starting automatic irrigation."))
                    history_irrigation = load_json(HISTORY_FILE, [])
                    if not history_irrigation or history_irrigation[-1].get("end_time") is not None:
                        new_irrigation = {
                            "location": selected_city,
                            "plot_index": 0,
                            "crop": crop_key,
                            "start_time": datetime.now(vn_tz).isoformat(),
                            "end_time": None,
                        }
                        history_irrigation.append(new_irrigation)
                        save_json(HISTORY_FILE, history_irrigation)
                    if st.button(_("⏹ Dừng tưới", "⏹ Stop irrigation")):
                        history_irrigation = load_json(HISTORY_FILE, [])
                        for i in reversed(range(len(history_irrigation))):
                            if history_irrigation[i].get("location") == selected_city and history_irrigation[i].get("end_time") is None:
                                history_irrigation[i]["end_time"] = datetime.now(vn_tz).isoformat()
                                save_json(HISTORY_FILE, history_irrigation)
                                st.success(_("🚰 Đã dừng tưới.", "🚰 Irrigation stopped."))
                                break
                else:
                    st.info(_("🌿 Độ ẩm đất đủ, không cần tưới.", "🌿 Soil moisture adequate, no irrigation needed."))
                    history_irrigation = load_json(HISTORY_FILE, [])
                    if history_irrigation and history_irrigation[-1].get("end_time") is None:
                        history_irrigation[-1]["end_time"] = datetime.now(vn_tz).isoformat()
                        save_json(HISTORY_FILE, history_irrigation)
            else:
                st.warning(_("⚠️ Hệ thống đang ở chế độ thủ công.", "⚠️ System is in manual mode."))
        else:
            st.info(_("🕒 Không phải giờ tưới.", "🕒 Not watering time."))

    st.subheader(_("📜 Lịch sử tưới nước", "📜 Irrigation History"))
    irrigation_hist = load_json(HISTORY_FILE, [])
    filtered_irrigation = [r for r in irrigation_hist if r.get("location") == selected_city]
    if filtered_irrigation:
        df_irrig = pd.DataFrame(filtered_irrigation)
        if "start_time" in df_irrig.columns:
            df_irrig["start_time"] = pd.to_datetime(df_irrig["start_time"])
        if "end_time" in df_irrig.columns:
            df_irrig["end_time"] = pd.to_datetime(df_irrig["end_time"])
        st.dataframe(df_irrig.sort_values(by="start_time", ascending=False))
    else:
        st.info(_("Chưa có lịch sử tưới cho khu vực này.", "No irrigation history for this location."))

# -----------------------
# Kết thúc
# -----------------------
st.markdown("---")
st.markdown(_("© 2025 Ngô Nguyễn Định Tường", "© 2025 Ngo Nguyen Dinh Tuong"))
st.markdown(_("© 2025 Mai Phúc Khang", "© 2025 Mai Phuc Khang"))

