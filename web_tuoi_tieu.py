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
import io
# --- Language fallback to avoid errors ---
if 'lang' not in globals():
    lang = "English"
if 'vi' not in globals():
    vi = (lang == "Tiếng Việt")
def _(vi_text, en_text):
    return vi_text if vi else en_text



# -----------------------
# Config & helpers
# -----------------------
st.set_page_config(page_title="Smart Irrigation WebApp", layout="wide")

# --- I18N ---
lang = st.sidebar.selectbox("🌐 Language / Ngôn ngữ", ["Tiếng Việt", "English"])
vi = lang == "Tiếng Việt"
def _(vi_text, en_text):
    try:
        return vi_text if lang == "Tiếng Việt" else en_text
    except:
        return en_text

# Files
DATA_FILE = "crop_data.json"
HISTORY_FILE = "history_irrigation.json"
FLOW_FILE = "flow_data.json"  # lưu dữ liệu lưu lượng (esp32) theo thời gian
CONFIG_FILE = "config.json"   # lưu cấu hình chung: khung giờ tưới + chế độ
UPLOAD_DIR = "data_uploads"   # nơi lưu file Excel upload
os.makedirs(UPLOAD_DIR, exist_ok=True)

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

# Timezone
vn_tz = pytz.timezone("Asia/Ho_Chi_Minh")

# -----------------------
# Helper: giữ dữ liệu trong vòng N ngày (mặc định 365)
# -----------------------
def filter_recent_list(lst, time_key, days=365):
    try:
        cutoff = datetime.now(vn_tz) - timedelta(days=days)
    except Exception:
        cutoff = datetime.utcnow() - timedelta(days=days)
    out = []
    for item in lst:
        ts = item.get(time_key) or item.get("start_time") or item.get("time") or item.get("timestamp")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts)
        except Exception:
            try:
                dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")
            except Exception:
                try:
                    dt = pd.to_datetime(ts)
                except Exception:
                    continue
        # Ensure timezone
        if hasattr(dt, "tzinfo") and dt.tzinfo is None:
            dt = vn_tz.localize(dt)
        # pandas Timestamp handling
        try:
            if hasattr(dt, "tz_localize") and getattr(dt, "tzinfo", None) is None:
                dt = dt.tz_localize(vn_tz)
        except Exception:
            pass
        if dt >= cutoff:
            out.append(item)
    return out

# -----------------------
# Helpers for Excel/CSV ingestion
# -----------------------
def normalize_cols(df):
    df2 = df.copy()
    df2.columns = [str(c).strip() for c in df2.columns]
    colmap = {}
    for c in df2.columns:
        cl = c.lower()
        if cl in ["timestamp", "time", "datetime", "date_time"]:
            colmap[c] = "timestamp"
        elif "temp" in cl or "temperature" in cl:
            colmap[c] = "sensor_temp"
        elif "hum" in cl and ("soil" not in cl):
            colmap[c] = "air_humidity"
        elif "soil" in cl or "moist" in cl or "soil_moist" in cl or "sensor_hum" in cl:
            colmap[c] = "sensor_hum"
        elif "flow" in cl or "lpm" in cl or "water_flow" in cl:
            colmap[c] = "flow"
        elif cl in ["location", "site", "city"]:
            colmap[c] = "location"
        elif "pump" in cl:
            colmap[c] = "pump_state"
    df2 = df2.rename(columns=colmap)
    return df2

def ingest_file_to_data(path):
    hist = load_json(HISTORY_FILE, [])
    flow = load_json(FLOW_FILE, [])
    appended_hist = 0
    appended_flow = 0

    try:
        if path.lower().endswith(".csv"):
            df = pd.read_csv(path)
        else:
            df = pd.read_excel(path)
    except Exception:
        try:
            df = pd.read_csv(path)
        except Exception:
            return (0,0)

    if df is None or df.empty:
        return (0,0)
    df = normalize_cols(df)

    for _, row in df.iterrows():
        ts = None
        if "timestamp" in row and pd.notna(row["timestamp"]):
            try:
                ts = pd.to_datetime(row["timestamp"]).isoformat()
            except:
                ts = None
        if ts is None:
            for c in df.columns:
                if str(c).lower() in ["date", "day"] and pd.notna(row[c]):
                    try:
                        ts = pd.to_datetime(row[c]).isoformat()
                        break
                    except:
                        pass
        loc = None
        if "location" in row and pd.notna(row["location"]):
            loc = str(row["location"])
        else:
            loc = ""

        # sensor data
        if ("sensor_hum" in row and pd.notna(row["sensor_hum"])) or ("sensor_temp" in row and pd.notna(row["sensor_temp"])) or ("air_humidity" in row and pd.notna(row["air_humidity"])):
            record = {}
            record["timestamp"] = ts if ts else datetime.now(vn_tz).isoformat()
            try:
                record["sensor_hum"] = float(row["sensor_hum"]) if "sensor_hum" in row and pd.notna(row["sensor_hum"]) else (float(row["air_humidity"]) if "air_humidity" in row and pd.notna(row["air_humidity"]) else None)
            except:
                record["sensor_hum"] = None
            try:
                record["sensor_temp"] = float(row["sensor_temp"]) if "sensor_temp" in row and pd.notna(row["sensor_temp"]) else None
            except:
                record["sensor_temp"] = None
            record["location"] = loc or ""
            hist.append(record)
            appended_hist += 1

        # flow
        if "flow" in row and pd.notna(row["flow"]):
            try:
                flow_val = float(row["flow"])
            except:
                flow_val = None
            if flow_val is not None:
                recf = {"time": ts if ts else datetime.now(vn_tz).isoformat(), "flow": flow_val, "location": loc or ""}
                flow.append(recf)
                appended_flow += 1

        # pump state in file -> append to history as special record
        if "pump_state" in row and pd.notna(row["pump_state"]):
            # Save pump state as a special history record for display
            rec = {"timestamp": ts if ts else datetime.now(vn_tz).isoformat(), "event": "pump_state", "value": str(row["pump_state"]), "location": loc or ""}
            hist.append(rec)

    # trim and save
    hist_trimmed = filter_recent_list(hist, "timestamp", days=365)
    flow_trimmed = filter_recent_list(flow, "time", days=365)
    save_json(HISTORY_FILE, hist_trimmed)
    save_json(FLOW_FILE, flow_trimmed)
    return (appended_hist, appended_flow)

# -----------------------
# Load persistent data (và lọc lịch sử chỉ 1 năm gần nhất)
# -----------------------
crop_data = load_json(DATA_FILE, {})
_raw_history = load_json(HISTORY_FILE, [])
_raw_flow = load_json(FLOW_FILE, [])
history_data = filter_recent_list(_raw_history, "timestamp", days=365)
flow_data = filter_recent_list(_raw_flow, "time", days=365)
save_json(HISTORY_FILE, history_data)
save_json(FLOW_FILE, flow_data)

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
except Exception:
    st.warning(_("❌ Không tìm thấy logo.png", "❌ logo.png not found"))

now = datetime.now(vn_tz)
st.markdown(f"<h2 style='text-align: center; font-size: 50px;'>🌾 { _('Hệ thống tưới tiêu nông nghiệp thông minh', 'Smart Agricultural Irrigation System') } 🌾</h2>", unsafe_allow_html=True)
st.markdown(f"<h3>⏰ { _('Thời gian hiện tại', 'Current time') }: {now.strftime('%d/%m/%Y %H:%M:%S')}</h3>", unsafe_allow_html=True)

# -----------------------
# Sidebar - role, auth & upload & export
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

st.sidebar.markdown("---")
st.sidebar.markdown(_("📥 Upload file Excel/CSV hàng ngày (nếu có)", "📥 Upload daily Excel/CSV (optional)"))
uploaded_files = st.sidebar.file_uploader(_("Chọn 1 hoặc nhiều file", "Select one or multiple files"), type=["xlsx", "xls", "csv"], accept_multiple_files=True)

if uploaded_files:
    total_h = total_f = 0
    for up in uploaded_files:
        # Save file
        save_path = os.path.join(UPLOAD_DIR, up.name)
        if os.path.exists(save_path):
            base, ext = os.path.splitext(up.name)
            save_path = os.path.join(UPLOAD_DIR, f"{base}_{int(datetime.now().timestamp())}{ext}")
        with open(save_path, "wb") as fout:
            fout.write(up.getbuffer())
        h_added, f_added = ingest_file_to_data(save_path)
        total_h += h_added
        total_f += f_added
    st.sidebar.success(_(f"Đã ingest: {total_h} bản ghi cảm biến, {total_f} bản ghi lưu lượng", f"Ingested: {total_h} sensor records, {total_f} flow records"))
    # reload history_data & flow_data into memory
    history_data = filter_recent_list(load_json(HISTORY_FILE, []), "timestamp", days=365)
    flow_data = filter_recent_list(load_json(FLOW_FILE, []), "time", days=365)

# Export history button (only when user requests)
st.sidebar.markdown("---")
st.sidebar.markdown(_("📤 Xuất lịch sử (Excel)", "📤 Export history (Excel)"))
export_scope = st.sidebar.selectbox(_("Chọn phạm vi xuất", "Select export scope"), [_("Khu vực hiện tại", "Current location"), _("Toàn bộ", "All locations")])
if st.sidebar.button(_("📥 Xuất file Excel lịch sử", "📥 Export Excel history")):
    # prepare dataframes
    hist = load_json(HISTORY_FILE, [])
    flow = load_json(FLOW_FILE, [])
    df_hist = pd.DataFrame(hist)
    df_flow = pd.DataFrame(flow)
    if export_scope == _("Khu vực hiện tại", "Current location"):
        df_hist = df_hist[df_hist.get("location", "") == selected_city] if not df_hist.empty else df_hist
        df_flow = df_flow[df_flow.get("location", "") == selected_city] if not df_flow.empty else df_flow
    # create excel in-memory
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="xlsxwriter") as writer:
        if not df_hist.empty:
            df_hist.to_excel(writer, sheet_name="history_irrigation", index=False)
        if not df_flow.empty:
            df_flow.to_excel(writer, sheet_name="flow_data", index=False)
        # include crops and config for reference
        pd.DataFrame([config]).to_excel(writer, sheet_name="config", index=False)
        pd.DataFrame.from_dict(crop_data, orient="index").to_excel(writer, sheet_name="crop_data", index=True)
        writer.save()
    out.seek(0)
    filename = f"export_history_{selected_city}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx" if export_scope == _("Khu vực hiện tại", "Current location") else f"export_history_all_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    st.sidebar.download_button(label=_("Tải file Excel lịch sử", "Download Excel history"), data=out, file_name=filename, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# -----------------------
# Auto-refresh every 30 minutes using session_state
# -----------------------
REFRESH_INTERVAL_SECONDS = 30 * 60  # 30 minutes
if "last_auto_refresh" not in st.session_state:
    st.session_state["last_auto_refresh"] = datetime.now(vn_tz)
else:
    elapsed = (datetime.now(vn_tz) - st.session_state["last_auto_refresh"]).total_seconds()
    if elapsed >= REFRESH_INTERVAL_SECONDS:
        st.session_state["last_auto_refresh"] = datetime.now(vn_tz)
        st.experimental_rerun()

# -----------------------
# Locations & crops (same)
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
# -----------------------
# Crop management UI + controller features (unchanged behavior mostly)
# -----------------------
st.header(_("🌱 Quản lý cây trồng", "🌱 Crop Management"))
mode_flag = config.get("mode", "auto")

# Controller: add/update plantings
if user_type == _("Người điều khiển", "Control Administrator"):
    st.subheader(_("Thêm / Cập nhật vùng trồng", "Add / Update Plantings"))
    plot_name = st.text_input(_("Tên khu vực con (plot) (ví dụ: Khu A, Khu B)", "Sub-plot name (e.g. Plot A, Plot B)"), value="")
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
                crop_entry = {"crop": add_crop_key, "planting_date": add_planting_date.isoformat(), "plot_name": plot_name}
                crop_data[selected_city]["plots"].append(crop_entry)
                save_json(DATA_FILE, crop_data)
                st.success(_("Đã thêm cây vào khu vực.", "Crop added to location."))
    else:
        crop_display_names = [crop_names[k] for k in crops.keys()]
        selected_crop_display = st.selectbox(_("🌱 Chọn loại nông sản:", "🌱 Select crop type:"), crop_display_names)
        selected_crop = next(k for k, v in crop_names.items() if v == selected_crop_display)
        planting_date = st.date_input(_("📅 Ngày gieo trồng:", "📅 Planting date:"), value=date.today())
        if st.button(_("💾 Lưu thông tin trồng", "💾 Save planting info")):
            crop_entry = {"crop": selected_crop, "planting_date": planting_date.isoformat(), "plot_name": plot_name}
            if selected_city not in crop_data:
                crop_data[selected_city] = {"plots": [crop_entry], "mode": mode_flag}
            else:
                crop_data[selected_city].setdefault("plots", []).append(crop_entry)
            save_json(DATA_FILE, crop_data)
            st.success(_("Đã lưu thông tin trồng.", "Planting info saved."))

    # Show all plantings (not only last one)
    st.subheader(_("📚 Tất cả thông tin trồng trong khu vực", "📚 All plantings in the location"))
    plots_all = crop_data.get(selected_city, {}).get("plots", [])
    if plots_all:
        rows_show = []
        for idx, p in enumerate(plots_all):
            crop_k = p.get("crop")
            pd_iso = p.get("planting_date")
            plotn = p.get("plot_name", "")
            try:
                pd_date = date.fromisoformat(pd_iso)
            except:
                pd_date = date.today()
            rows_show.append({"index": idx, "plot_name": plotn, "crop": crop_names.get(crop_k, crop_k), "planting_date": pd_date.strftime("%d/%m/%Y")})
        st.dataframe(pd.DataFrame(rows_show))
    else:
        st.info(_("Chưa có vùng trồng nào trong khu vực này.", "No plots in this location yet."))

# Controller - planting history (1 year) + pump per plot
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
                    "plot_name": p.get("plot_name", ""),
                    "crop": crop_names.get(crop_k, crop_k),
                    "planting_date": pd_date.strftime("%d/%m/%Y")
                })
        if rows_hist:
            st.dataframe(pd.DataFrame(rows_hist))
        else:
            st.info(_("Không có cây được trồng trong vòng 1 năm tại khu vực này.", "No plantings within last 1 year in this location."))
    else:
        st.info(_("Chưa có vùng trồng nào trong khu vực này.", "No plots in this location yet."))

# Controller - per-plot pump control
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
            plotn = p.get("plot_name", "")
            label = f"Plot {i} {('- '+plotn) if plotn else ''} - {crop_names.get(crop_k, crop_k)} - {pd_iso}"
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
# Monitoring officer UI (keeps previous logic)
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
            min_d, max_d = crops.get(crop_k, (0,0))
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
                "crop": crop_names.get(crop_k, crop_k),
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
        st.dataframe(df_irrig.sort_values(by="start_time", ascending=False) if "start_time" in df_irrig.columns else df_irrig)
    else:
        st.info(_("Chưa có lịch sử tưới cho khu vực này.", "No irrigation history for this location."))

    st.header(_("📊 Biểu đồ lịch sử cảm biến", "📊 Sensor History Charts"))
    history_data = load_json(HISTORY_FILE, [])
    flow_data = load_json(FLOW_FILE, [])
    filtered_hist = [h for h in history_data if h.get("location") == selected_city]
    filtered_flow = [f for f in flow_data if f.get("location") == selected_city]
    df_hist_all = pd.DataFrame(filtered_hist)
    df_flow_all = pd.DataFrame(filtered_flow)

    if not df_hist_all.empty and 'timestamp' in df_hist_all.columns and 'sensor_hum' in df_hist_all.columns and 'timestamp' in df_hist_all.columns:
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
# Weather (Open-Meteo) + charts + compare (kept similar)
# -----------------------
st.header(_("🌦 Thời tiết hiện tại", "🌦 Current Weather"))

def fetch_open_meteo(lat, lon):
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&current=temperature_2m,relativehumidity_2m,precipitation"
        "&timezone=auto"
    )
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json()

try:
    wdata = fetch_open_meteo(latitude, longitude)
    current = wdata.get("current", {})
    temp = current.get("temperature_2m")
    rh = current.get("relativehumidity_2m")
    rain = current.get("precipitation")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(_("🌡 Nhiệt độ (°C)", "🌡 Temperature (°C)"), f"{temp} °C" if temp is not None else "N/A")
    with col2:
        st.metric(_("💧 Độ ẩm không khí (%)", "💧 Air Humidity (%)"), f"{rh} %" if rh is not None else "N/A")
    with col3:
        st.metric(_("🌧 Lượng mưa (mm)", "🌧 Precipitation (mm)"), f"{rain} mm" if rain is not None else "N/A")

except Exception as e:
    st.error(_("Lỗi khi lấy dữ liệu thời tiết:", "Error fetching weather data:") + f" {e}")

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
# MQTT Client for receiving data from ESP32-WROOM (restored with more topics)
# -----------------------
mqtt_broker = "broker.hivemq.com"
mqtt_port = 1883

# Topics we listen to - allow multiple sensor topics
mqtt_topics = [
    ("esp32/soil_moisture", 0),
    ("esp32/temperature", 0),
    ("esp32/humidity", 0),
    ("esp32/water_flow", 0),
    ("esp32/pump_state", 0),
    # you can add "esp32/device/<id>/..." etc.
]

# Live containers
live_soil_moisture = []
live_water_flow = []
live_temperature = []
live_air_humidity = []
pump_states = []  # records of pump state changes
last_seen = {}  # topic -> datetime for connectivity checks

# Helper: parse payload which might be plain number or JSON
def parse_payload(payload_str):
    # Try JSON
    try:
        data = json.loads(payload_str)
        return data
    except:
        # try float
        try:
            v = float(payload_str)
            return v
        except:
            return payload_str  # fallback raw

def on_connect(client, userdata, flags, rc):
    print(f"Connected to MQTT broker with result code {rc}")
    for t, q in mqtt_topics:
        client.subscribe(t, q)

def on_message(client, userdata, msg):
    topic = msg.topic
    payload_raw = msg.payload.decode(errors="ignore")
    now_iso = datetime.now(vn_tz).isoformat()
    # update last seen by topic (or by device if topic includes device id)
    last_seen[topic] = datetime.now(vn_tz)
    parsed = parse_payload(payload_raw)
    # if parsed is dict, look for keys
    if isinstance(parsed, dict):
        # soil moisture
        if "soil_moisture" in parsed or "sensor_hum" in parsed:
            val = parsed.get("soil_moisture") or parsed.get("sensor_hum")
            try:
                val = float(val)
            except:
                val = None
            if val is not None:
                live_soil_moisture.append({"timestamp": now_iso, "sensor_hum": val, "location": selected_city})
                hist = load_json(HISTORY_FILE, [])
                hist.append({"timestamp": now_iso, "sensor_hum": val, "sensor_temp": parsed.get("sensor_temp"), "location": selected_city})
                save_json(HISTORY_FILE, filter_recent_list(hist, "timestamp", days=365))
        # temperature
        if "temperature" in parsed or "sensor_temp" in parsed:
            val = parsed.get("temperature") or parsed.get("sensor_temp")
            try:
                val = float(val)
            except:
                val = None
            if val is not None:
                live_temperature.append({"timestamp": now_iso, "sensor_temp": val, "location": selected_city})
                hist = load_json(HISTORY_FILE, [])
                # append a combined record if sensible
                hist.append({"timestamp": now_iso, "sensor_temp": val, "location": selected_city})
                save_json(HISTORY_FILE, filter_recent_list(hist, "timestamp", days=365))
        # air humidity
        if "humidity" in parsed and not ("soil" in parsed):
            try:
                val = float(parsed.get("humidity"))
            except:
                val = None
            if val is not None:
                live_air_humidity.append({"timestamp": now_iso, "air_humidity": val, "location": selected_city})
                hist = load_json(HISTORY_FILE, [])
                hist.append({"timestamp": now_iso, "air_humidity": val, "location": selected_city})
                save_json(HISTORY_FILE, filter_recent_list(hist, "timestamp", days=365))
        # flow
        if "flow" in parsed or "water_flow" in parsed:
            val = parsed.get("flow") or parsed.get("water_flow")
            try:
                val = float(val)
            except:
                val = None
            if val is not None:
                live_water_flow.append({"time": now_iso, "flow": val, "location": selected_city})
                flow = load_json(FLOW_FILE, [])
                flow.append({"time": now_iso, "flow": val, "location": selected_city})
                save_json(FLOW_FILE, filter_recent_list(flow, "time", days=365))
        # pump state
        if "pump" in parsed or "pump_state" in parsed:
            st_val = parsed.get("pump") or parsed.get("pump_state")
            pump_states.append({"time": now_iso, "pump_state": str(st_val), "location": selected_city})
            hist = load_json(HISTORY_FILE, [])
            hist.append({"timestamp": now_iso, "event": "pump_state", "value": str(st_val), "location": selected_city})
            save_json(HISTORY_FILE, filter_recent_list(hist, "timestamp", days=365))

    else:
        # payload is scalar or string
        # determine by topic
        if "soil_moisture" in topic:
            try:
                val = float(parsed)
                live_soil_moisture.append({"timestamp": now_iso, "sensor_hum": val, "location": selected_city})
                hist = load_json(HISTORY_FILE, [])
                hist.append({"timestamp": now_iso, "sensor_hum": val, "location": selected_city})
                save_json(HISTORY_FILE, filter_recent_list(hist, "timestamp", days=365))
            except:
                pass
        elif "temperature" in topic:
            try:
                val = float(parsed)
                live_temperature.append({"timestamp": now_iso, "sensor_temp": val, "location": selected_city})
                hist = load_json(HISTORY_FILE, [])
                hist.append({"timestamp": now_iso, "sensor_temp": val, "location": selected_city})
                save_json(HISTORY_FILE, filter_recent_list(hist, "timestamp", days=365))
            except:
                pass
        elif "humidity" in topic:
            try:
                val = float(parsed)
                live_air_humidity.append({"timestamp": now_iso, "air_humidity": val, "location": selected_city})
                hist = load_json(HISTORY_FILE, [])
                hist.append({"timestamp": now_iso, "air_humidity": val, "location": selected_city})
                save_json(HISTORY_FILE, filter_recent_list(hist, "timestamp", days=365))
            except:
                pass
        elif "water_flow" in topic or "flow" in topic:
            try:
                val = float(parsed)
                live_water_flow.append({"time": now_iso, "flow": val, "location": selected_city})
                flow = load_json(FLOW_FILE, [])
                flow.append({"time": now_iso, "flow": val, "location": selected_city})
                save_json(FLOW_FILE, filter_recent_list(flow, "time", days=365))
            except:
                pass
        elif "pump" in topic:
            pump_states.append({"time": now_iso, "pump_state": str(parsed), "location": selected_city})
            hist = load_json(HISTORY_FILE, [])
            hist.append({"timestamp": now_iso, "event": "pump_state", "value": str(parsed), "location": selected_city})
            save_json(HISTORY_FILE, filter_recent_list(hist, "timestamp", days=365))

# MQTT loop in background thread
def mqtt_thread():
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(mqtt_broker, mqtt_port, 60)
        client.loop_forever()
    except Exception as e:
        print("MQTT connect failed:", e)

threading.Thread(target=mqtt_thread, daemon=True).start()

# -----------------------
# Connectivity status & pump state display
# -----------------------
st.header(_("🔌 Trạng thái kết nối ESP32 & trạng thái bơm", "🔌 ESP32 Connection & Pump Status"))

# show last seen for each topic we track
status_rows = []
now_dt = datetime.now(vn_tz)
for t, _ in mqtt_topics:
    last = last_seen.get(t)
    if last:
        age = (now_dt - last).total_seconds()
        online = age <= 120  # consider online if last message within 2 minutes
        status_rows.append({"topic": t, "last_seen": last.astimezone(vn_tz).strftime("%d/%m/%Y %H:%M:%S"), "status": _("Online","Online") if online else _("Offline","Offline")})
    else:
        status_rows.append({"topic": t, "last_seen": "-", "status": _("Offline","Offline")})
st.table(pd.DataFrame(status_rows))

# Latest pump state
if pump_states:
    last_pump = pump_states[-1]
    st.markdown(f"**{_('Trạng thái bơm mới nhất', 'Latest pump state')}:** {last_pump.get('pump_state')} — {_('thời gian', 'time')}: {last_pump.get('time')}")
else:
    st.info(_("Chưa có bản ghi trạng thái bơm.", "No pump state records."))

# -----------------------
# Current live charts (show restored sensor streams)
# -----------------------
st.header(_("📊 Biểu đồ dữ liệu cảm biến hiện tại", "📊 Current Sensor Data Charts"))

# Build dataframes from live lists and persistent files (so page refresh keeps historical)
# Combine in-memory live buffers with stored history to show continuity
hist_store = load_json(HISTORY_FILE, [])
flow_store = load_json(FLOW_FILE, [])

# soil moisture (history)
soil_records = [r for r in hist_store if "sensor_hum" in r and (r.get("location") == selected_city or r.get("location") == "")]
df_soil = pd.DataFrame(soil_records)
if not df_soil.empty:
    df_soil["timestamp"] = pd.to_datetime(df_soil["timestamp"], errors="coerce")
    df_soil = df_soil.sort_values("timestamp")
# temperature
temp_records = [r for r in hist_store if "sensor_temp" in r and (r.get("location") == selected_city or r.get("location") == "")]
df_temp = pd.DataFrame(temp_records)
if not df_temp.empty:
    df_temp["timestamp"] = pd.to_datetime(df_temp["timestamp"], errors="coerce")
    df_temp = df_temp.sort_values("timestamp")
# flow
flow_records = [r for r in flow_store if (r.get("location") == selected_city or r.get("location") == "")]
df_flow = pd.DataFrame(flow_records)
if not df_flow.empty:
    df_flow["time"] = pd.to_datetime(df_flow["time"], errors="coerce")
    df_flow = df_flow.sort_values("time")

col1, col2 = st.columns(2)
with col1:
    st.markdown(_("### Độ ẩm đất (Sensor Humidity)", "### Soil Moisture"))
    if not df_soil.empty and "sensor_hum" in df_soil.columns:
        series = df_soil.set_index("timestamp")["sensor_hum"].astype(float)
        st.line_chart(series)
        st.write(_("Giá trị mới nhất:", "Latest value:"), series.iloc[-1])
    else:
        st.info(_("Chưa có dữ liệu độ ẩm đất nhận từ ESP32 hoặc file upload.", "No soil moisture data received from ESP32 or uploads."))

with col2:
    st.markdown(_("### Lưu lượng nước (Water Flow)", "### Water Flow"))
    if not df_flow.empty and "flow" in df_flow.columns:
        seriesf = df_flow.set_index("time")["flow"].astype(float)
        st.line_chart(seriesf)
        st.write(_("Giá trị mới nhất:", "Latest value:"), seriesf.iloc[-1])
    else:
        st.info(_("Chưa có dữ liệu lưu lượng nước nhận từ ESP32 hoặc file upload.", "No water flow data received from ESP32 or uploads."))

# Show temperature and air humidity charts below
col3, col4 = st.columns(2)
with col3:
    st.markdown(_("### Nhiệt độ (Temperature)", "### Temperature"))
    if not df_temp.empty and "sensor_temp" in df_temp.columns:
        st.line_chart(df_temp.set_index("timestamp")["sensor_temp"].astype(float))
    else:
        st.info(_("Chưa có dữ liệu nhiệt độ.", "No temperature data."))

with col4:
    st.markdown(_("### Độ ẩm không khí (Air Humidity)", "### Air Humidity"))
    air_records = [r for r in hist_store if "air_humidity" in r and (r.get("location") == selected_city or r.get("location") == "")]
    df_air = pd.DataFrame(air_records)
    if not df_air.empty:
        df_air["timestamp"] = pd.to_datetime(df_air["timestamp"], errors="coerce")
        st.line_chart(df_air.set_index("timestamp")["air_humidity"].astype(float))
    else:
        st.info(_("Chưa có dữ liệu độ ẩm không khí.", "No air humidity data."))

# -----------------------
# End
# -----------------------
st.markdown("---")
st.markdown(_("© 2025 Ngô Nguyễn Định Tường", "© 2025 Ngo Nguyen Dinh Tuong"))
st.markdown(_("© 2025 Mai Phúc Khang", "© 2025 Mai Phuc Khang"))
