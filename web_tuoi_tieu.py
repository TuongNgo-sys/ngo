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
import matplotlib.pyplot as plt  # <-- added for plotting
#import seaborn as sns
#from streamlit_autorefresh import st_autorefresh
# -----------------------
# Config & helpers
# -----------------------
st.set_page_config(page_title="Smart Irrigation WebApp", layout="wide")
#st_autorefresh(interval=60 * 1000, key="init_refresh")

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

# -----------------------
# Helper: giữ dữ liệu trong vòng N ngày (mặc định 365)
# -----------------------
def filter_recent_list(lst, time_key, days=365):
    """
    lst: list of dicts
    time_key: key string containing ISO timestamp (e.g. 'timestamp' or 'time')
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
            continue
        try:
            dt = datetime.fromisoformat(ts)
        except:
            try:
                dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")
            except:
                continue
        # ensure timezone-aware comparison
        if dt.tzinfo is None:
            dt = vn_tz.localize(dt)
        if dt >= cutoff:
            out.append(item)
    return out

# Timezone
vn_tz = pytz.timezone("Asia/Ho_Chi_Minh")

# Hàm thêm record lưu lượng vào flow_data
def add_flow_record(flow_val, location=""):
    now_iso = datetime.now(vn_tz).isoformat()
    new_record = {
        "time": now_iso,
        "flow": flow_val,
        "location": location,
    }
    flow = load_json(FLOW_FILE, [])
    flow.append(new_record)
    # lưu luôn sau khi thêm
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

# --- NEW: For controller - choose sub-plot (khu vực con) and view planting history (1 year)
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

    # --- NEW: Show planting history (last 1 year) for controller
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
        # create friendly labels
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
                # lưu lịch sử tưới bắt đầu cho plot này
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
                # tìm bản ghi mở gần nhất cho location & plot_index
                for i in reversed(range(len(history_irrigation))):
                    rec = history_irrigation[i]
                    if rec.get("location") == selected_city and rec.get("plot_index") == selected_plot_index and rec.get("end_time") is None:
                        history_irrigation[i]["end_time"] = datetime.now(vn_tz).isoformat()
                        save_json(HISTORY_FILE, history_irrigation)
                        st.success(_("🚰 Đã dừng bơm cho khu vực.", "🚰 Pump stopped for selected plot."))
                        break
                else:
                    st.info(_("Không tìm thấy phiên tưới đang mở cho khu vực này.", "No open irrigation session found for this plot."))

# ======================
# Phần cho Người giám sát
# ======================
if user_type == _("Người giám sát", "Monitoring Officer"):
    st.subheader(_("📜 Lịch sử tưới nước", "📜 Irrigation History"))
    irrigation_hist = load_json(HISTORY_FILE, [])
    filtered_irrigation = [r for r in irrigation_hist if r.get("location") == selected_city]
    if filtered_irrigation:
        df_irrig = pd.DataFrame(filtered_irrigation)
        if "start_time" in df_irrig.columns:
            df_irrig["start_time"] = pd.to_datetime(
                df_irrig["start_time"], errors='coerce'
            ).dt.strftime("%H:%M")
        # Chỉ giữ giờ tưới và khu vực + đổi tên cột song ngữ
        df_irrig = df_irrig[["start_time", "location"]]
        df_irrig.rename(columns={
            "start_time": _("Giờ tưới", "Start Time"),
            "location": _("Khu vực", "Location")
        }, inplace=True)

        # Căn giữa, ẩn index và thêm màu nền xen kẽ
        styled_df = df_irrig.sort_values(
            by=_("Giờ tưới", "Start Time"), ascending=False
        ).style.set_properties(**{'text-align': 'center'}) \
         .hide(axis='index') \
         .apply(lambda x: ['background-color: #f9f9f9' if i % 2 == 0 else '' for i in range(len(x))], axis=0)

        st.dataframe(styled_df, use_container_width=True)
    else:
        st.info(_("Chưa có lịch sử tưới cho khu vực này.", "No irrigation history for this location."))


# ======================
# Phần cho Người điều khiển
# ======================
elif user_type == _("Người điều khiển", "Controller"):
    # ... các phần điều khiển tưới của bạn ở đây ...

    # Lịch sử tưới
    st.subheader(_("📜 Lịch sử tưới nước", "📜 Irrigation History"))
    irrigation_hist = load_json(HISTORY_FILE, [])
    filtered_irrigation = [r for r in irrigation_hist if r.get("location") == selected_city]
    if filtered_irrigation:
        df_irrig = pd.DataFrame(filtered_irrigation)
        if "start_time" in df_irrig.columns:
            df_irrig["start_time"] = pd.to_datetime(
                df_irrig["start_time"], errors='coerce'
            ).dt.strftime("%H:%M")
        # Chỉ giữ giờ tưới và khu vực + đổi tên cột song ngữ
        df_irrig = df_irrig[["start_time", "location"]]
        df_irrig.rename(columns={
            "start_time": _("Giờ tưới", "Start Time"),
            "location": _("Khu vực", "Location")
        }, inplace=True)

        # Căn giữa, ẩn index và thêm màu nền xen kẽ
        styled_df = df_irrig.sort_values(
            by=_("Giờ tưới", "Start Time"), ascending=False
        ).style.set_properties(**{'text-align': 'center'}) \
         .hide(axis='index') \
         .apply(lambda x: ['background-color: #f9f9f9' if i % 2 == 0 else '' for i in range(len(x))], axis=0)

        st.dataframe(styled_df, use_container_width=True)
    else:
        st.info(_("Chưa có lịch sử tưới cho khu vực này.", "No irrigation history for this location."))

