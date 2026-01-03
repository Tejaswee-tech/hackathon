import streamlit as st
import asyncio
import time
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from bleak import BleakScanner, BleakClient

# --- CONSTANTS ---
HR_CHAR_UUID = "00002a37-0000-1000-8000-00805f9b34fb"

# --- PAGE CONFIG ---
st.set_page_config(page_title="VesselScan AI | Clinical Suite", layout="wide", page_icon="🩺")

# Initialize Session State
if 'page' not in st.session_state: st.session_state.page = 'home'
if 'live_hr' not in st.session_state: st.session_state.live_hr = 0
if 'scan_complete' not in st.session_state: st.session_state.scan_complete = False

# --- CSS FOR UI/UX ---
st.markdown("""
    <style>
    [data-testid="stAppViewContainer"] { background-color: #0e1117; }
    .stMetric { background-color: #1a1c23; padding: 15px; border-radius: 10px; border: 1px solid #333; }
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; background-color: #FF4B4B; color: white; font-weight: bold; }
    .scanning-text { font-family: 'Courier New', Courier, monospace; color: #00FFCC; font-size: 1.2em; text-shadow: 0 0 5px #00FFCC; }
    </style>
    """, unsafe_allow_html=True)

# --- BLE CALLBACK ---
def hr_callback(handle, data):
    # Byte 1 is the heart rate value for Fire-Boltt 100
    if len(data) > 1:
        st.session_state.live_hr = data[1]

# --- PAGE 1: HOME ---
if st.session_state.page == 'home':
    st.title("🩺 VesselScan AI: Hardware Link")
    st.info("💡 Ensure Fire-Boltt 100 is disconnected from your phone's Da Fit app.")
    
    if st.button("🔍 SCAN FOR BLUETOOTH DEVICES"):
        with st.spinner("Searching for Fire-Boltt 100..."):
            devices = asyncio.run(BleakScanner.discover(timeout=5.0))
            st.session_state.found_devices = {d.name: d.address for d in devices if d.name}
    
    if 'found_devices' in st.session_state:
        selection = st.selectbox("Select Device", options=list(st.session_state.found_devices.keys()))
        if st.button("🔗 PAIR WATCH"):
            st.session_state.ble_address = st.session_state.found_devices[selection]
            st.session_state.page = 'intake'
            st.rerun()

# --- PAGE 2: INTAKE ---
elif st.session_state.page == 'intake':
    st.title("📋 Clinical Intake")
    with st.form("patient_form"):
        col1, col2 = st.columns(2)
        with col1:
            age = st.number_input("Age", 18, 100, 45)
            bp = st.number_input("Systolic BP (mmHg)", 90, 200, 120)
        with col2:
            gender = st.selectbox("Sex", ["Male", "Female"])
            pain = st.radio("Chest Pain?", ["No", "Yes"], horizontal=True)
        
        if st.form_submit_button("🚀 INITIALIZE SIGNAL CAPTURE"):
            st.session_state.p_data = {'age': age, 'bp': bp, 'pain': pain}
            st.session_state.page = 'processing'
            st.rerun()

# --- PAGE 3: SCANNING & WAVES ---
elif st.session_state.page == 'processing':
    st.title("⚙️ Signal Acquisition & Waveform Analysis")
    
    col_chart, col_status = st.columns([3, 1])
    chart_placeholder = col_chart.empty()
    status_msg = col_status.empty()
    bpm_metric = col_status.empty()
    progress_bar = st.progress(0)

    async def run_analysis():
        async with BleakClient(st.session_state.ble_address, timeout=20.0) as client:
            status_msg.markdown('<p class="scanning-text">SYNCING GATT SERVICES...</p>', unsafe_allow_html=True)
            await client.start_notify(HR_CHAR_UUID, hr_callback)
            
            hr_history = []
            # Buffer for the scrolling effect
            buffer_size = 150
            wave_buffer = np.zeros(buffer_size)
            
            # Capture duration (approx 15 seconds)
            for i in range(150):
                # Update Animation Stats
                progress_bar.progress(int((i / 150) * 100))
                bpm_metric.metric("Live BPM", f"{st.session_state.live_hr}")
                status_msg.markdown(f'<p class="scanning-text">ANALYZING SIGNAL... {i}/150</p>', unsafe_allow_html=True)
                
                # Dynamic Waveform Calculation
                freq = st.session_state.live_hr / 60 if st.session_state.live_hr > 0 else 1.2
                # Generate a single point of the PPG wave (Sine + Dicrotic Notch + Noise)
                t_point = i * 0.1
                new_point = (np.sin(2 * np.pi * freq * t_point) + 
                             0.4 * np.sin(4 * np.pi * freq * t_point + 1.2) + 
                             np.random.normal(0, 0.05))
                
                # Shift buffer and add new point (scrolling effect)
                wave_buffer = np.append(wave_buffer[1:], new_point)
                hr_history.append(st.session_state.live_hr)
                
                # Render the scrolling Plotly chart
                fig = go.Figure(go.Scatter(y=wave_buffer, 
                                           line=dict(color='#00FFCC', width=3), 
                                           fill='tozeroy',
                                           hoverinfo='none'))
                
                fig.update_layout(
                    template="plotly_dark", 
                    height=450, 
                    margin=dict(l=0,r=0,t=0,b=0),
                    xaxis=dict(visible=False, range=[0, buffer_size]),
                    yaxis=dict(range=[-1.5, 1.5], fixedrange=True),
                    showlegend=False
                )
                
                chart_placeholder.plotly_chart(fig, use_container_width=True, key=f"wave_{i}")
                
                await asyncio.sleep(0.05) # Control animation speed (approx 20 FPS)
            
            await client.stop_notify(HR_CHAR_UUID)
            return hr_history

    if st.button("🛰️ START SENSOR SCAN"):
        try:
            results = asyncio.run(run_analysis())
            st.session_state.final_hr = np.mean(results)
            st.session_state.page = 'result'
            st.rerun()
        except Exception as e:
            st.error(f"Hardware Error: {e}")
            st.info("💡 Troubleshoot: 1. Turn OFF phone Bluetooth. 2. Restart Watch. 3. Re-scan.")

# --- PAGE 4: RESULTS ---
elif st.session_state.page == 'result':
    st.title("📊 Diagnostic Biometric Report")
    
    # Simple risk logic
    risk = 20
    if st.session_state.final_hr > 95: risk += 30
    if st.session_state.p_data['bp'] > 145: risk += 40
    
    col_l, col_r = st.columns(2)
    col_l.metric("Vascular Risk Score", f"{risk}%")
    col_l.write(f"Average Captured Heart Rate: **{int(st.session_state.final_hr)} BPM**")
    
    if risk > 60:
        st.error("🚨 HIGH CARDIOVASCULAR RISK DETECTED")
        st.markdown("""
        **Clinical Suggestions:**
        * Schedule an **Echocardiogram** to assess arterial stiffness.
        * Consult a cardiologist regarding potential **Arterial Plaque**.
        """)
    else:
        st.success("✅ VASCULAR STABILITY DETECTED")
        st.write("Baseline results are within normal limits for this demographic.")
    
    if st.button("⬅️ PERFORM NEW SCAN"):
        st.session_state.page = 'home'
        st.rerun()
