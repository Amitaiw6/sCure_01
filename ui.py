import customtkinter as ctk
import threading
import time
import random
import socket
import math
import csv
import os
from datetime import datetime
from tkinter import filedialog



# ================= IMPORT HARDWARE MODULES =================
try:
    from io_board import IOBoard
    from temperature_control import TemperatureController
    from throttle_control import Throttle
    from led_driver_pwm import LEDDriverPWM
    from air_control import AirController
    # Import the new Intake Controller
    from air_control_IN import AirControllerIN

    HARDWARE_AVAILABLE = True
except ImportError as e:
    print(f"Hardware modules not found or dependencies missing: {e}")
    print("Running in GUI-only mode.")
    HARDWARE_AVAILABLE = False
except Exception as e:
    print(f"Error initializing hardware libraries: {e}")
    HARDWARE_AVAILABLE = False

try:
    from PIL import Image
except ImportError:
    print("Pillow library not found. Please run: pip install Pillow")
    Image = None

import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

class CureBoxUI(ctk.CTk):
    
    """
    ULTIMATE VERSION: 
    1. Added AirControllerIN (Intake) integration.
    2. Throttle logic fixed (One-time command, ensures state).
    3. LED Cooling Relay disabled in auto process.
    4. UI Fixed (Sliders, Logo, Scrollable).
    """
    
    def __init__(self):
        
        super().__init__()

        self.title("Cure Box Control UI")
        self.geometry("800x600")
        self.canvas_size = 220

        
        # Uncomment for Raspberry Pi Fullscreen
        # self.attributes('-fullscreen', True)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        # --- Hardware Initialization ---
        self.hw_connected = False
        if HARDWARE_AVAILABLE:
            try:
                print("Initializing Hardware...")
                self.io = IOBoard(debug=True)
                self.temp_ctrl = TemperatureController(self.io)
                self.throttle = Throttle()
                self.led_driver = LEDDriverPWM()
                self.air_controller = AirController()     # Main/Exhaust Air
                self.air_in = AirControllerIN()           # NEW: Intake/Cooling Air
                
                self.hw_connected = True
                print("Hardware Initialized Successfully.")
            except Exception as e:
                print(f"CRITICAL HARDWARE ERROR: {e}")
                self.hw_connected = False

        self.door_open = False
        self.current_temperature = 25.0
        self.current_humidity = 0.0
        
        # --- Throttle State Memory (To prevent repeated clicking) ---
        self.last_throttle_state = None  # Can be "OPEN", "CLOSED", or None

        # Network Info
        self.network_status = "Connected"
        self.current_ssid = "CureLab_5G"
        self.current_ip = self._get_ip()
        self.wifi_networks = ["Production_WiFi", "Guest_Network", "Office_Main", "Lab_Equipment"]

        self.analytics_data = { "time": [], "temp": [], "humidity": [] }
        self.is_process_running = False
        self.process_state = {} 
        self.is_edit_mode = False
        self.waiting_for_temp = True
        self.custom_steps = []
        self.current_step_idx = 0

        # Default Data
        self.jobs = [
            {"name": "Job_Titan_01", "material": "Resin Tough", "dry_time": 60, "cure_time": 120},
            {"name": "Job_Dental_Bridge", "material": "Dental Cast", "dry_time": 30, "cure_time": 45}
        ]
        self.materials = [
            {"name": "Standard Grey Resin", "pwm": 80, "dry_time": 45, "dry_temp": 50, "pre_heat_time": 0, "pre_heat_temp": 0, "cure_time": 60, "cool_temp": 30},
            {"name": "Dental Castable", "pwm": 100, "dry_time": 120, "dry_temp": 60, "pre_heat_time": 10, "pre_heat_temp": 40, "cure_time": 180, "cool_temp": 25},
             {"name": "Demo Fast Mode", "pwm": 10, "dry_time": 1, "dry_temp": 35, "pre_heat_time": 0, "pre_heat_temp": 35, "cure_time": 5, "cool_temp": 28}
        ]
        # זיכרון מצב חומרה למניעת תקיעות (שורות חדשות להוספה)
        self._last_hw_values = {
            "uv": None, "fan": None, "intake": None, "exhaust": None
        }

        self.grid_columnconfigure(0, weight=2)
        self.grid_columnconfigure(1, weight=5)
        self.grid_rowconfigure(0, weight=1)

        self._build_left_menu()
        self._build_right_area()
        
        # Start the background loop for sensor reading
        self._start_sensor_loop()

    def _get_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"

    # ================= HELPER: SMART THROTTLE CONTROL =================
    def _set_throttle(self, desired_state):
        """
        Sends command to throttle ONLY if the state needs to change.
        desired_state: "OPEN" or "CLOSED"
        """
        if desired_state == self.last_throttle_state:
            return # Do nothing, already in state

        print(f"[AUTO] Changing Throttle to: {desired_state}")
        
        if self.hw_connected:
            if desired_state == "OPEN":
                self.throttle.open()
            elif desired_state == "CLOSED":
                self.throttle.close()
        
        self.last_throttle_state = desired_state

    # ================= LEFT MENU =================
    def _build_left_menu(self):
        self.left_frame = ctk.CTkFrame(self, corner_radius=0)
        self.left_frame.grid(row=0, column=0, sticky="nsew")

        # Load Logo
        logo_loaded = False
        if Image is not None:
            try:
                current_dir = os.path.dirname(os.path.abspath(__file__))
                image_path = os.path.join(current_dir, "image_8.png")
                if os.path.exists(image_path):
                    pil_image = Image.open(image_path)
                    self.logo_image = ctk.CTkImage(light_image=pil_image, dark_image=pil_image, size=(130, 130))
                    ctk.CTkLabel(self.left_frame, text="", image=self.logo_image).pack(pady=(20, 20))
                    logo_loaded = True
            except Exception:
                pass

        if not logo_loaded:
            ctk.CTkLabel(self.left_frame, text="sCure", font=ctk.CTkFont(size=32, weight="bold")).pack(pady=(30, 30))

        self.menu_buttons = {}
        menu_items = ["Select Job", "System", "Analytics", "Settings", "Network"]
        
        for name in menu_items:
            btn = ctk.CTkButton(
                self.left_frame, text=name, height=60, corner_radius=12,
                fg_color="transparent", text_color=("gray10", "gray90"),
                hover_color=("gray70", "gray30"), anchor="center",
                font=ctk.CTkFont(size=16, weight="bold"),
                command=lambda n=name: self._switch_screen(n)
            )
            btn.pack(pady=8, fill="x", padx=20)
            self.menu_buttons[name] = btn

        self._highlight_menu("Select Job")

    def _switch_screen(self, screen):
        if self.is_process_running and screen != "System": return
        self._highlight_menu(screen)
        
        if screen == "Select Job": self._home_screen()
        elif screen == "Analytics": self._open_analytics()
        elif screen == "Network": self._open_network_screen()
        elif screen == "Settings": self._open_hardware_settings()
        else:
            self._clear()
            ctk.CTkLabel(self.content_frame, text=f"{screen} Screen", font=ctk.CTkFont(size=20)).pack(pady=100)

    def _highlight_menu(self, active):
        for name, btn in self.menu_buttons.items():
            if name == active: btn.configure(fg_color=("gray75", "gray25"))
            else: btn.configure(fg_color="transparent")

    # ================= RIGHT AREA =================
    def _build_right_area(self):
        self.right_frame = ctk.CTkFrame(self, corner_radius=0, fg_color=("gray95", "gray10"))
        self.right_frame.grid(row=0, column=1, sticky="nsew")

        self.status_bar = ctk.CTkFrame(self.right_frame, height=50, corner_radius=0, fg_color="transparent")
        self.status_bar.pack(fill="x", padx=20, pady=10)

        self.lbl_network = ctk.CTkLabel(self.status_bar, text="📶", font=ctk.CTkFont(size=20), text_color="#2ecc71")
        self.lbl_network.pack(side="right", padx=(15, 0))

        self.lbl_temp = ctk.CTkLabel(self.status_bar, text="--.- °C", font=ctk.CTkFont(size=16, weight="bold"))
        self.lbl_temp.pack(side="right", padx=(15, 0))
        
        self.btn_door = ctk.CTkButton(self.status_bar, text="DOOR: CHECKING", width=120, height=30, 
                                      fg_color="gray", state="disabled")
        self.btn_door.pack(side="right", padx=15)

        self.content_frame = ctk.CTkFrame(self.right_frame, fg_color="transparent")
        self.content_frame.pack(expand=True, fill="both", padx=10, pady=10)

        self._home_screen()

    # ================= HARDWARE SETTINGS SCREEN =================
    def _open_hardware_settings(self):
        self._clear()
        
        top_bar = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        top_bar.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(top_bar, text="Manual Hardware Control", font=ctk.CTkFont(size=24, weight="bold")).pack(side="left")

        scroll_hw = ctk.CTkScrollableFrame(self.content_frame, fg_color="transparent")
        scroll_hw.pack(fill="both", expand=True)

        if not self.hw_connected:
             ctk.CTkLabel(scroll_hw, text="⚠️ HARDWARE DISCONNECTED / SIMULATION MODE", text_color="orange").pack(pady=5)

        # --- Heater Control ---
        self._create_section(scroll_hw, "Heater Control", [
            ("Heater ON", "#c0392b", self._hw_heater_on),
            ("Heater OFF", "#7f8c8d", self._hw_heater_off)
        ])

        # --- LED Cooling (FPGA Relay) ---
        self._create_section(scroll_hw, "LED Cooling Relay (FPGA)", [
            ("Cooling ON", "#2980b9", self._hw_led_cool_on),
            ("Cooling OFF", "#7f8c8d", self._hw_led_cool_off)
        ])

        # --- Fans & Air Intake ---
        fan_frame = ctk.CTkFrame(scroll_hw, corner_radius=10)
        fan_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(fan_frame, text="Air Flow Control", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=5)
        
        def create_slider_row(parent, label, min_v, max_v, default_v, callback):
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=5)
            row.grid_columnconfigure(1, weight=1) 
            ctk.CTkLabel(row, text=label, width=130, anchor="w").grid(row=0, column=0, padx=(0, 10))
            val_lbl = ctk.CTkLabel(row, text=str(int(default_v)), width=40, font=ctk.CTkFont(weight="bold"))
            val_lbl.grid(row=0, column=2, padx=(10, 0))
            def cmd_wrapper(value):
                val_lbl.configure(text=str(int(value)))
                callback(value)
            slider = ctk.CTkSlider(row, from_=min_v, to=max_v, command=cmd_wrapper)
            slider.set(default_v)
            slider.grid(row=0, column=1, sticky="ew")

        create_slider_row(fan_frame, "Internal Fan (%)", 0, 100, 50, self._hw_set_fan)
        create_slider_row(fan_frame, "Air Exhaust (Main) (%)", 0, 100, 50, self._hw_set_air)
        
        # --- NEW: AIR INTAKE SLIDER ---
        create_slider_row(fan_frame, "Air Intake (Blower) (%)", 0, 100, 0, self._hw_set_air_in)


        # --- Throttle Motor ---
        motor_frame = ctk.CTkFrame(scroll_hw, corner_radius=10)
        motor_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(motor_frame, text="Throttle Motor Control", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=5)
        
        m_btn_row = ctk.CTkFrame(motor_frame, fg_color="transparent")
        m_btn_row.pack(fill="x", padx=10, pady=(5, 10))
        ctk.CTkButton(m_btn_row, text="OPEN", width=80, fg_color="#2ecc71", command=self._hw_motor_open).pack(side="left", padx=5)
        ctk.CTkButton(m_btn_row, text="CLOSE", width=80, fg_color="#e67e22", command=self._hw_motor_close).pack(side="left", padx=5)
        ctk.CTkButton(m_btn_row, text="STOP", width=80, fg_color="#c0392b", command=self._hw_motor_stop).pack(side="left", padx=5)
        
        create_slider_row(motor_frame, "Motor Speed (PWM)", 0, 255, 150, self._hw_set_motor_speed)

        # --- LED Driver PWM ---
        led_pwm_frame = ctk.CTkFrame(scroll_hw, corner_radius=10)
        led_pwm_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(led_pwm_frame, text="UV LED Driver (HLG-480H-40B)", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=5)
        
        create_slider_row(led_pwm_frame, "UV Power (%)", 0, 100, 0, self._hw_set_uv_pwm)

    def _create_section(self, parent, title, buttons):
        frame = ctk.CTkFrame(parent, corner_radius=10)
        frame.pack(fill="x", pady=5)
        ctk.CTkLabel(frame, text=title, font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=(5,0))
        btn_row = ctk.CTkFrame(frame, fg_color="transparent")
        btn_row.pack(fill="x", padx=10, pady=10)
        for text, color, cmd in buttons:
            ctk.CTkButton(btn_row, text=text, fg_color=color, command=cmd).pack(side="left", fill="x", expand=True, padx=5)

    # --- Hardware Interface Wrappers ---
    def _hw_heater_on(self):
        if self.hw_connected: self.io.heater_on()
        else: print("SIM: Heater ON")

    def _hw_heater_off(self):
        if self.hw_connected: self.io.heater_off()
        else: print("SIM: Heater OFF")

    def _hw_led_cool_on(self):
        if self.hw_connected: self.io.led_on()
        else: print("SIM: Relay LED ON")

    def _hw_led_cool_off(self):
        if self.hw_connected: self.io.led_off()
        else: print("SIM: Relay LED OFF")

    def _hw_set_fan(self, value):
        if self.hw_connected: self.io.set_fan(int(value))
        else: print(f"SIM: Internal Fan {int(value)}%")

    def _hw_set_air(self, value):
        # Existing AirController (Exhaust)
        if self.hw_connected: self.air_controller.set_air_percent(float(value))
        else: print(f"SIM: Air Exhaust {int(value)}%")
    
    def _hw_set_air_in(self, value):
        # NEW: AirControllerIN (Intake)
        if self.hw_connected and hasattr(self, 'air_in'): 
            self.air_in.set_air_percent(float(value))
        else: 
            print(f"SIM: Air Intake IN {int(value)}%")

    def _hw_motor_open(self):
        if self.hw_connected: self.throttle.open()
        else: print("SIM: Motor OPEN")

    def _hw_motor_close(self):
        if self.hw_connected: self.throttle.close()
        else: print("SIM: Motor CLOSE")

    def _hw_motor_stop(self):
        if self.hw_connected: self.throttle.stop()
        else: print("SIM: Motor STOP")

    def _hw_set_motor_speed(self, value):
        if self.hw_connected: self.throttle.set_speed(int(value))
        else: print(f"SIM: Motor Speed {int(value)}")

    def _hw_set_uv_pwm(self, value):
        if self.hw_connected: self.led_driver.set_duty(float(value))
        else: print(f"SIM: UV PWM {int(value)}%")


    # ================= HOME & PROCESS =================
    def _home_screen(self):
        self._clear()
        
        # Header Section
        header_frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        header_frame.pack(fill="x", pady=(10, 20), padx=20)
        
        text_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        text_frame.pack(side="left", fill="y")
        ctk.CTkLabel(text_frame, text="Welcome", font=ctk.CTkFont(size=32, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(text_frame, text="Select an action to begin processing", font=ctk.CTkFont(size=16), text_color="gray").pack(anchor="w")

        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            logo_path = os.path.join(current_dir, "Stratasys_logo_black_RGB.png")
            if os.path.exists(logo_path):
                pil_logo = Image.open(logo_path)
                logo_img = ctk.CTkImage(light_image=pil_logo, dark_image=pil_logo, size=(220, 60))
                logo_label = ctk.CTkLabel(header_frame, text="", image=logo_img)
                logo_label.pack(side="right", padx=10)
        except Exception as e:
            print(f"Error loading Stratasys logo: {e}")

        # Buttons Container
        btn_container = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        btn_container.pack(fill="x", padx=20)
        
        icon_jobs = None
        icon_mat = None
        try:
            path_j = os.path.join(current_dir, "icon_jobs.png") 
            path_m = os.path.join(current_dir, "icon_materials.png")
            if os.path.exists(path_j): icon_jobs = ctk.CTkImage(Image.open(path_j), size=(40,40))
            if os.path.exists(path_m): icon_mat = ctk.CTkImage(Image.open(path_m), size=(40,40))
        except: pass

        btn_jobs = ctk.CTkButton(
            btn_container, text="Active Jobs", image=icon_jobs, compound="top",
            font=ctk.CTkFont(size=22, weight="bold"),
            fg_color="#2b2b2b", hover_color="#3a3a3a", border_width=2, border_color="#3498db",   
            height=150, corner_radius=15, command=self._open_job_list
        )
        btn_jobs.pack(side="left", fill="x", expand=True, padx=(0, 10))

        btn_materials = ctk.CTkButton(
            btn_container, text="Material Library", image=icon_mat, compound="top",
            font=ctk.CTkFont(size=22, weight="bold"),
            fg_color="#2b2b2b", hover_color="#3a3a3a", border_width=2, border_color="#e67e22",   
            height=150, corner_radius=15, command=self._open_material_list
        )
        btn_materials.pack(side="left", fill="x", expand=True, padx=(10, 0))

        status_frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        status_frame.pack(fill="both", expand=True, pady=30, padx=20)
        ctk.CTkLabel(status_frame, text="System Status: Ready", text_color="gray").pack(anchor="s", pady=10)

    # ================= PROCESS EXECUTION (FIXED LOGIC) =================
    def _start_process_execution(self, material):
        self._clear()
        self.is_process_running = True
        
        self._stop_all_hardware()
        
        dashboard_bg = "#212121"
        self.content_frame.configure(fg_color=dashboard_bg)
        
        scroll_process = ctk.CTkScrollableFrame(self.content_frame, fg_color="transparent")
        scroll_process.pack(fill="both", expand=True)

        self.process_state = {
            "material": material, "stage": "RAMP_TO_DRY", "start_time": 0, "duration": 0, 
            "target_temp": material['dry_temp'], "message": "PREPARING..."
        }
        
        self.lbl_process_stage = ctk.CTkLabel(scroll_process, text="PREPARING...", font=ctk.CTkFont(size=24, weight="bold"))
        self.lbl_process_stage.pack(pady=(20, 10))

        self.canvas_size = 220 
        self.process_canvas = ctk.CTkCanvas(scroll_process, width=self.canvas_size, height=self.canvas_size, bg=dashboard_bg, highlightthickness=0)
        self.process_canvas.pack(pady=10)

        self.lbl_process_details = ctk.CTkLabel(scroll_process, text="--:--", font=ctk.CTkFont(size=18))
        self.lbl_process_details.pack(pady=5)

        ctk.CTkButton(scroll_process, text="ABORT PROCESS", fg_color="#c0392b", hover_color="#e74c3c", height=50, font=ctk.CTkFont(size=16, weight="bold"), command=self._abort_process).pack(pady=20)
        
        self.after(500, self._process_tick)

    def _process_tick(self):
        if not self.is_process_running: return
        
        state = self.process_state
        mat = state["material"]
        current_temp = self.current_temperature 
        
        # --- STATE MACHINE WITH FIXED LOGIC ---
        if state["stage"] == "RAMP_TO_DRY":
            self._hw_set_motor_speed(150)
            target = mat['dry_temp']
            state["message"] = f"HEATING (DRY): {int(current_temp)}/{target}°C"
            self.lbl_process_details.configure(text="Ramping up temp...")
            
            if self.hw_connected:
                self.temp_ctrl.start(target)    
                self.io.set_fan(100)            # Fan 100%
                self._set_throttle("CLOSED")      # Fixed: Use _set_throttle to avoid repeating
            
            progress = min(1.0, current_temp / target) if target > 0 else 1.0
            if abs(current_temp - target) <= 2.0:
                state["stage"] = "DRYING"
                state["start_time"] = time.time()
                state["duration"] = mat['dry_time'] * 60 

        elif state["stage"] == "DRYING":
            

            state["message"] = "DRYING PHASE"
            if self.hw_connected: 
                self.temp_ctrl.start(mat['dry_temp'])
                self.air_in.set_air_percent(30)            
                self._set_throttle("OPEN") 
                self.io.set_fan(100)      
            
            elapsed = time.time() - state["start_time"]
            remaining = max(0, state["duration"] - elapsed)
            mins = int(remaining // 60)
            secs = int(remaining % 60)
            self.lbl_process_details.configure(text=f"Time Left: {mins}:{secs:02d}")
            progress = elapsed / state["duration"]
            
            if remaining <= 0:
                self.air_in.set_air_percent(0)
                self._set_throttle("CLOSED") 
                next_temp = mat.get('pre_heat_temp', 0)
                state["stage"] = "PRE_HEATING" 
                state["target_temp"] = next_temp
                

        elif state["stage"] == "PRE_HEATING":
            target = state["target_temp"]
            state["message"] = f"PRE_HEATING: {int(current_temp)}/{target}°C"
            self.io.set_fan(100)  
            if self.hw_connected: 
                self.temp_ctrl.start(target)
                
            diff = abs(target - mat['pre_heat_temp'])
            curr_diff = abs(current_temp - mat['pre_heat_temp'])
            progress = curr_diff / diff if diff > 0 else 1.0
            
            if abs(current_temp - target) <= 2.0:
                state["stage"] = "HEATING"
                state["start_time"] = time.time()
                state["duration"] = mat['pre_heat_time'] * 60


        elif state["stage"] == "HEATING":
            

            state["message"] = "HEATING"
            if self.hw_connected: 
                self.temp_ctrl.start(mat['pre_heat_temp'])               

            elapsed = time.time() - state["start_time"]
            remaining = max(0, state["duration"] - elapsed)
            mins = int(remaining // 60)
            secs = int(remaining % 60)
            self.lbl_process_details.configure(text=f"Time Left: {mins}:{secs:02d}")
            progress = elapsed / state["duration"]
            
            
            if remaining <= 0:
                
                state["duration"] = mat['cure_time'] * 60
                next_temp = mat.get('pre_heat_temp', 0)
                state["stage"] = "CURING"
                self.io.heater_off()
                self.led_driver.set_duty(mat['pwm'])
                state["start_time"] = time.time()
                state["target_temp"] = next_temp
                
                

        elif state["stage"] == "CURING":
            self._hw_set_air(100)
            state["message"] = f"UV CURING ({mat['pwm']}%)"
            elapsed = time.time() - state["start_time"]
            remaining = max(0, state["duration"] - elapsed)
            mins = int(remaining // 60)
            secs = int(remaining % 60)
            self.lbl_process_details.configure(text=f"Time Left: {mins}:{secs:02d}")
            progress = elapsed / state["duration"]
            
            if self.hw_connected: 
                self.temp_ctrl.start(state["target_temp"])
                
            
            if remaining <= 0:
                state["stage"] = "COOLING"
                if self.hw_connected:
                    self.led_driver.set_duty(0)
                    self.temp_ctrl.stop() 
                    self.io.set_fan(100) 
                    self.io.heater_off()
                    self.air_in.set_air_percent(100)
                    self._set_throttle("OPEN") 

        elif state["stage"] == "COOLING":
            target = mat['cool_temp']
            state["message"] = f"COOLING: {int(current_temp)} -> {target}°C"
            self.lbl_process_details.configure(text="Cooling down...")
            
            if self.hw_connected:
                self.io.heater_off()
                self.io.set_fan(100)            
                self.air_controller.set_air_percent(100) 
                # LED COOLING REMOVED (self.io.led_on() deleted)
                self._set_throttle("OPEN")      # Open to cool
            
            start_cool_temp = 60 
            total_drop = start_cool_temp - target
            current_drop = start_cool_temp - current_temp
            progress = current_drop / total_drop if total_drop > 0 else 0
            
            if current_temp <= target + 2.0:
                state["stage"] = "DONE"
                self._stop_all_hardware()

        elif state["stage"] == "DONE":
            progress = 1.0
            state["message"] = "PROCESS COMPLETE"
            self.lbl_process_details.configure(text="Safe to open door")
            self.is_process_running = False 
            ctk.CTkButton(self.content_frame, text="FINISH", command=self._home_screen, fg_color="#2ecc71").pack(pady=10)

        self.lbl_process_stage.configure(text=state["message"])
        self._draw_pie_chart(progress, state["stage"])
        
        if self.is_process_running: self.after(200, self._process_tick)

    def _stop_all_hardware(self):
        if self.hw_connected:
            self.temp_ctrl.stop()
            self.io.heater_off()
            self.led_driver.set_duty(0)
            self.air_controller.set_air_percent(0)
            if hasattr(self, 'air_in'): self.air_in.set_air_percent(0) # Stop Intake
            self.throttle.stop()
            self.last_throttle_state = None # Reset state

    def _abort_process(self):
        self.is_process_running = False
        self._stop_all_hardware()
        self._home_screen()

    # ================= VISUALS =================
    def _draw_pie_chart(self, progress, stage_name):
        self.process_canvas.delete("all")
        cx, cy = self.canvas_size/2, self.canvas_size/2
        stroke_width = 20 
        r = self.canvas_size/2 - stroke_width/2 - 5
        self.process_canvas.create_oval(cx-r, cy-r, cx+r, cy+r, outline="#606060", width=stroke_width)
        angle = progress * 360
        color = "#3498db"
        if "DRY" in stage_name: color = "#e67e22"
        elif "CURE" in stage_name: color = "#9b59b6"
        elif "COOL" in stage_name: color = "#34495e"
        elif "DONE" in stage_name: color = "#2ecc71"
        if angle > 0:
            if angle >= 360:
                 self.process_canvas.create_oval(cx-r, cy-r, cx+r, cy+r, outline=color, width=stroke_width)
            else:
                self.process_canvas.create_arc(cx-r, cy-r, cx+r, cy+r, start=90, extent=-angle, style="arc", outline=color, width=stroke_width)
        percent_text = f"{int(progress * 100)}%"
        self.process_canvas.create_text(cx, cy-5, text=percent_text, fill="white", font=("Arial", 38, "bold"))
        clean_stage_name = stage_name.split('_')[0]
        self.process_canvas.create_text(cx, cy+30, text=clean_stage_name, fill="#b0b0b0", font=("Arial", 14, "bold"))

    # ================= SENSOR LOOP =================
    def _start_sensor_loop(self):
        def update():
            if self.hw_connected:
                t = self.io.read_temp_c()
                if t is not None: self.current_temperature = t
                raw_interlock = self.io.read_interlock_raw()
                if raw_interlock is not None:
                    is_closed = (raw_interlock & 0b1) != 0
                    self.door_open = not is_closed
            else:
                self.current_temperature += random.uniform(-0.1, 0.1)
                self.door_open = False 
            
            self.lbl_temp.configure(text=f"{self.current_temperature:.1f} °C")
            
            if self.door_open:
                self.btn_door.configure(text="DOOR: OPEN", fg_color="#e74c3c")
            else:
                self.btn_door.configure(text="DOOR: CLOSED", fg_color="#2ecc71")

            if not self.is_process_running:
                timestamp = datetime.now().strftime('%H:%M:%S')
                self.analytics_data['time'].append(timestamp)
                self.analytics_data['temp'].append(self.current_temperature)
                if len(self.analytics_data['time']) > 30:
                     self.analytics_data['time'].pop(0)
                     self.analytics_data['temp'].pop(0)

            self.after(1000, update)
        update()

    # ================= OTHER SCREENS (Network, Analytics...) =================
    def _open_network_screen(self):
        self._clear()
        title = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        title.pack(fill="x", pady=10)
        ctk.CTkLabel(title, text="Network Settings", font=ctk.CTkFont(size=24, weight="bold")).pack(side="left")
        ctk.CTkButton(title, text="Scan for Networks", width=120, command=self._open_network_screen).pack(side="right")
        status_card = ctk.CTkFrame(self.content_frame, corner_radius=10)
        status_card.pack(fill="x", padx=10, pady=10)
        ctk.CTkLabel(status_card, text="Current Connection", font=ctk.CTkFont(size=14, weight="bold"), text_color="gray").pack(anchor="w", padx=15, pady=(15, 5))
        row = ctk.CTkFrame(status_card, fg_color="transparent")
        row.pack(fill="x", padx=15, pady=(0, 15))
        ctk.CTkLabel(row, text="📶", font=ctk.CTkFont(size=30)).pack(side="left", padx=(0, 15))
        info = ctk.CTkFrame(row, fg_color="transparent")
        info.pack(side="left")
        ctk.CTkLabel(info, text=self.current_ssid, font=ctk.CTkFont(size=18, weight="bold"), text_color="#2ecc71").pack(anchor="w")
        ctk.CTkLabel(info, text=f"IP Address: {self.current_ip}", text_color="gray").pack(anchor="w")
        ctk.CTkButton(row, text="Disconnect", fg_color="#c0392b", hover_color="#e74c3c", width=100).pack(side="right")
        
        scroll_list = ctk.CTkScrollableFrame(self.content_frame)
        scroll_list.pack(expand=True, fill="both", padx=10, pady=5)
        for net in self.wifi_networks:
            item = ctk.CTkFrame(scroll_list, fg_color=("gray85", "gray17"))
            item.pack(fill="x", pady=5)
            ctk.CTkLabel(item, text=net, font=ctk.CTkFont(size=14)).pack(side="left", padx=15, pady=10)
            ctk.CTkButton(item, text="Connect", width=80, fg_color="#34495e").pack(side="right", padx=10)

    def _open_analytics(self):
        self._clear()
        title = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        title.pack(fill="x", pady=5)
        ctk.CTkLabel(title, text="System Analytics", font=ctk.CTkFont(size=24, weight="bold")).pack(side="left")
        fig = Figure(figsize=(5, 4), dpi=100)
        fig.patch.set_facecolor('#2b2b2b')
        ax1 = fig.add_subplot(111)
        ax1.set_facecolor('#2b2b2b')
        ax1.grid(True, color='white', alpha=0.1, linestyle='--')
        color_temp = '#ff5555'
        ax1.plot(self.analytics_data['temp'], color=color_temp, linewidth=2, label="Temp")
        ax1.set_ylabel('Temperature (°C)', color=color_temp, fontsize=10, fontweight='bold')
        ax1.tick_params(axis='y', labelcolor=color_temp, colors='white')
        ax1.tick_params(axis='x', colors='#a0a0a0')
        
        for ax in [ax1]:
            ax.spines['top'].set_visible(False)
            ax.spines['bottom'].set_color('#404040')
            ax.spines['left'].set_visible(False)
            ax.spines['right'].set_visible(False)
        fig.tight_layout()
        canvas = FigureCanvasTkAgg(fig, master=self.content_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=10)
        canvas.get_tk_widget().configure(background='#242424', highlightthickness=0)
        ctk.CTkButton(self.content_frame, text="📥 Export to CSV", fg_color="#2ecc71", height=50, command=self._export_csv).pack(fill="x", padx=40, pady=10)

    def _export_csv(self):
        filename = f"analytics_{datetime.now().strftime('%H%M%S')}.csv"
        try:
            with open(filename, mode='w', newline='') as file:
                writer = csv.writer(file)
                writer.writerow(["Timestamp", "Temperature"])
                rows = zip(self.analytics_data['time'], self.analytics_data['temp'])
                writer.writerows(rows)
            print(f"Exported to {filename}")
        except Exception as e:
            print(f"Error: {e}")

    # ================= MATERIAL LIST =================
    def _open_material_list(self):
        self._clear()
        # Same logic as before, using ScrollableFrame
        top_bar = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        top_bar.pack(fill="x", pady=10)
        ctk.CTkLabel(top_bar, text="Material Library", font=ctk.CTkFont(size=24, weight="bold")).pack(side="left")
        buttons_frame = ctk.CTkFrame(top_bar, fg_color="transparent")
        buttons_frame.pack(side="right")
        edit_btn_text = "Done" if self.is_edit_mode else "Edit List"
        ctk.CTkButton(buttons_frame, text=edit_btn_text, width=80, fg_color="#34495e", command=self._toggle_edit_mode).pack(side="right", padx=10)
        if not self.is_edit_mode:
            ctk.CTkButton(buttons_frame, text="+ New", width=80, fg_color="#2ecc71", command=self._show_new_material).pack(side="right")
        
        list_frame = ctk.CTkScrollableFrame(self.content_frame)
        list_frame.pack(expand=True, fill="both", pady=10)
        
        for mat in self.materials:
            card = ctk.CTkFrame(list_frame, fg_color=("gray85", "gray17"))
            card.pack(fill="x", pady=5, padx=5)
            ctk.CTkLabel(card, text=mat['name'], font=ctk.CTkFont(size=16, weight="bold")).pack(side="left", padx=10, pady=15)
            if self.is_edit_mode:
                 ctk.CTkButton(card, text="DELETE", width=100, fg_color="#c0392b", command=lambda m=mat: self._delete_material(m)).pack(side="right", padx=10)
            else:
                 ctk.CTkButton(card, text="SELECT", width=80, fg_color="#3498db", command=lambda m=mat: self._preview_material_dashboard(m)).pack(side="right", padx=10)
        ctk.CTkButton(self.content_frame, text="Back Home", command=self._home_screen, fg_color="transparent", border_width=1).pack(pady=5)

    def _toggle_edit_mode(self):
        self.is_edit_mode = not self.is_edit_mode
        self._open_material_list()

    def _delete_material(self, material):
        if material in self.materials:
            self.materials.remove(material)
            self._open_material_list()

    def _show_new_material(self):
        self._clear()
        ctk.CTkLabel(self.content_frame, text="Create New Profile", font=ctk.CTkFont(size=20, weight="bold")).pack(pady=10)
        form_scroll = ctk.CTkScrollableFrame(self.content_frame)
        form_scroll.pack(expand=True, fill="both", padx=10, pady=5)
        ctk.CTkLabel(form_scroll, text="Material Name").pack(anchor="w", padx=10)
        entry_name = ctk.CTkEntry(form_scroll)
        entry_name.pack(fill="x", padx=10, pady=(0, 10))
        sliders = {}
        def add_slider(key, label, min_v, max_v, default=0):
            frame = ctk.CTkFrame(form_scroll, fg_color="transparent")
            frame.pack(fill="x", padx=5, pady=2)
            lbl_val = ctk.CTkLabel(frame, text=f"{int(default)}", width=40, font=ctk.CTkFont(weight="bold"))
            lbl_val.pack(side="right")
            ctk.CTkLabel(frame, text=label).pack(side="left")
            s = ctk.CTkSlider(form_scroll, from_=min_v, to=max_v, number_of_steps=max_v-min_v)
            s.set(default)
            s.pack(fill="x", padx=10, pady=(0, 10))
            s.configure(command=lambda v, l=lbl_val: l.configure(text=f"{int(v)}"))
            sliders[key] = s
        add_slider("pwm", "UV Power (%)", 0, 100, 80)
        add_slider("dry_time", "Drying Time (min)", 0, 120, 30)
        add_slider("dry_temp", "Drying Temp (°C)", 20, 80, 45)
        add_slider("pre_heat_time", "Pre-Heat Time (min)", 0, 60, 0)
        add_slider("pre_heat_temp", "Pre-Heat Temp (°C)", 20, 80, 0)
        add_slider("cure_time", "Cure Time (min)", 0, 300, 60)
        add_slider("cool_temp", "Cooling Target (°C)", 0, 40, 25)
        def save_material():
            new_mat = {
                "name": entry_name.get() or "Custom Material",
                "pwm": int(sliders["pwm"].get()),
                "dry_time": int(sliders["dry_time"].get()),
                "dry_temp": int(sliders["dry_temp"].get()),
                "pre_heat_time": int(sliders["pre_heat_time"].get()),
                "pre_heat_temp": int(sliders["pre_heat_temp"].get()),
                "cure_time": int(sliders["cure_time"].get()),
                "cool_temp": int(sliders["cool_temp"].get()),
            }
            self.materials.append(new_mat)
            self._open_material_list()
        btn_row = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        btn_row.pack(fill="x", pady=10)
        ctk.CTkButton(btn_row, text="Save Profile", command=save_material, fg_color="#27ae60").pack(side="right", padx=10)
        ctk.CTkButton(btn_row, text="Cancel", command=self._open_material_list, fg_color="transparent", border_width=1).pack(side="left", padx=10)

    # ================= PREVIEW DASHBOARD =================
    def _preview_material_dashboard(self, material):
        self._clear()
        
        scroll_container = ctk.CTkScrollableFrame(self.content_frame, fg_color="transparent")
        scroll_container.pack(fill="both", expand=True, padx=0, pady=0)

        title_frame = ctk.CTkFrame(scroll_container, fg_color="transparent")
        title_frame.pack(fill="x", padx=10, pady=(10, 5))
        
        ctk.CTkLabel(title_frame, text=material['name'], font=ctk.CTkFont(size=24, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(title_frame, text="Process Configuration Preview", text_color="gray").pack(anchor="w")

        stats_frame = ctk.CTkFrame(scroll_container, corner_radius=15)
        stats_frame.pack(fill="x", padx=10, pady=10)
        stats_frame.grid_columnconfigure(0, weight=1)
        stats_frame.grid_columnconfigure(1, weight=1)

        def create_stat_item(parent, row, col, label_text, value_text, unit=""):
            f = ctk.CTkFrame(parent, fg_color="transparent")
            f.grid(row=row, column=col, sticky="nsew", padx=5, pady=5)
            ctk.CTkLabel(f, text=label_text, font=ctk.CTkFont(size=12, weight="bold"), text_color="gray").pack()
            ctk.CTkLabel(f, text=f"{value_text}{unit}", font=ctk.CTkFont(size=20, weight="bold"), text_color="#4a90e2").pack()

        create_stat_item(stats_frame, 0, 0, "UV POWER", material.get('pwm', 0), "%")
        create_stat_item(stats_frame, 0, 1, "CURE TIME", material.get('cure_time', 0), " min")
        ctk.CTkFrame(stats_frame, height=2, fg_color="gray30").grid(row=1, column=0, columnspan=2, sticky="ew", padx=20, pady=5)
        create_stat_item(stats_frame, 2, 0, "DRY TIME", material.get('dry_time', 0), " min")
        create_stat_item(stats_frame, 2, 1, "DRY TEMP", material.get('dry_temp', 0), "°C")

        ph_time = material.get('pre_heat_time', 0)
        row_idx = 3
        if ph_time > 0:
            create_stat_item(stats_frame, row_idx, 0, "PRE-HEAT TIME", ph_time, " min")
            create_stat_item(stats_frame, row_idx, 1, "PRE-HEAT TEMP", material.get('pre_heat_temp', 0), "°C")
            row_idx += 1
        create_stat_item(stats_frame, row_idx, 0, "COOLING TARGET", material.get('cool_temp', 0), "°C")

        btn_frame = ctk.CTkFrame(scroll_container, fg_color="transparent")
        btn_frame.pack(fill="x", pady=10, padx=10)
        ctk.CTkButton(btn_frame, text="INITIATE PROCESS", font=ctk.CTkFont(size=16, weight="bold"), height=50, fg_color="#2ecc71", hover_color="#27ae60", command=lambda: self._start_process_execution(material)).pack(side="right", fill="x", expand=True, padx=(10, 0))
        ctk.CTkButton(btn_frame, text="← Edit", height=50, fg_color="transparent", border_width=1, border_color="gray", command=self._open_material_list).pack(side="left", padx=(0, 10))

    # === החלפה של הפונקציה הקיימת ===
    def _open_job_list(self):
        self._clear()
        ctk.CTkLabel(
            self.content_frame,
            text="Custom Job Control",
            font=ctk.CTkFont(size=28, weight="bold")
        ).pack(pady=20)

        btn_usb = ctk.CTkButton(
            self.content_frame,
            text="📁 Load Process from USB (.csv)",
            height=80,
            fg_color="#3498db",
            hover_color="#2980b9",
            font=ctk.CTkFont(size=20, weight="bold"),
            command=self._load_process_from_usb
        )
        btn_usb.pack(pady=20, fill="x", padx=40)

        ctk.CTkButton(
            self.content_frame,
            text="← Back to Home",
            command=self._home_screen,
            fg_color="transparent",
            border_width=1
        ).pack(pady=10)

    def _load_process_from_usb(self):
        file_path = filedialog.askopenfilename(
            title="Select CSV File",
            filetypes=(("CSV files", "*.csv"), ("All files", "*.*"))
        )
        if not file_path:
            return

        try:
            custom_steps = []
            with open(file_path, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    custom_steps.append({
                        "action": row.get("Action", "Step"),
                        "duration": int(row.get("Minutes", 0)) * 60 + int(row.get("Seconds", 0)),
                        "target_temp": float(row.get("Temp", 25)),
                        "uv_pwm": float(row.get("UV_PWM", 0)),
                        "fan": int(row.get("Fan", 100)),
                        "intake": float(row.get("Intake", 0)),
                        "exhaust": float(row.get("Exhaust", 0)),
                        "throttle": row.get("Throttle", "CLOSED").upper()
                    })

            if custom_steps:
                self._start_custom_sequence(custom_steps)

        except Exception as e:
            print(f"CSV Error: {e}")

    def _start_custom_sequence(self, steps):
        self._clear()
        self.is_process_running = True
        self.waiting_for_temp = True
        self._stop_all_hardware()

        self.custom_steps = steps
        self.current_step_idx = 0

        self.lbl_process_stage = ctk.CTkLabel(
            self.content_frame,
            text="INITIATING...",
            font=ctk.CTkFont(size=24, weight="bold")
        )
        self.lbl_process_stage.pack(pady=10)

        self.process_canvas = ctk.CTkCanvas(
            self.content_frame,
            width=self.canvas_size,
            height=self.canvas_size,
            bg="#1a1a1a",
            highlightthickness=0
        )
        self.process_canvas.pack(pady=10)

        self.lbl_process_details = ctk.CTkLabel(
            self.content_frame,
            text="Waiting for Temperature...",
            font=ctk.CTkFont(size=16)
        )
        self.lbl_process_details.pack(pady=5)

        ctk.CTkButton(
            self.content_frame,
            text="ABORT PROCESS",
            fg_color="#c0392b",
            command=self._abort_process
        ).pack(pady=10)

        self._custom_tick()

    def _custom_tick(self):
        if not self.is_process_running:
            return

        try:
            step = self.custom_steps[self.current_step_idx]
            current = self.current_temperature
            target = step['target_temp']

            if self.waiting_for_temp:
                if abs(current - target) <= 2.0:
                    self.waiting_for_temp = False
                    self.step_start_time = time.time()
                    elapsed = 0
                    remaining = step['duration']
                else:
                    elapsed = 0
                    remaining = step['duration']
            else:
                elapsed = time.time() - self.step_start_time
                remaining = max(0, step['duration'] - elapsed)

            if self.hw_connected:
                self.temp_ctrl.start(target)
                self.led_driver.set_duty(step['uv_pwm'])
                self.io.set_fan(step['fan'])
                self.air_in.set_air_percent(step['intake'])
                self.air_controller.set_air_percent(step['exhaust'])
                self._set_throttle(step['throttle'])

                if "COOL" in step['action'].upper():
                    self.io.heater_off()

            temp_match = min(
                100,
                max(0, (1 - abs(target - current) / max(1, target)) * 100)
            ) if target > 25 else 100

            mins, secs = divmod(int(remaining), 60)
            stage_text = f"STEP {self.current_step_idx + 1}: {step['action']}"
            if self.waiting_for_temp:
                stage_text += " (STABILIZING...)"

            self.lbl_process_stage.configure(text=stage_text)
            self.lbl_process_details.configure(
                text=f"Time: {mins:02d}:{secs:02d} | Target: {target}°C | Match: {int(temp_match)}%"
            )

            progress = elapsed / step['duration'] if step['duration'] > 0 else 0
            self._draw_pie_chart(progress, step['action'])

            if remaining <= 0 and not self.waiting_for_temp:
                self.current_step_idx += 1
                if self.current_step_idx < len(self.custom_steps):
                    self.waiting_for_temp = True
                    self.last_throttle_state = None
                else:
                    self._finish_custom_process()
                    return

        except Exception as e:
            print(f"Tick Error: {e}")

        self.after(200, self._custom_tick)

    def _finish_custom_process(self):
        self.is_process_running = False
        self._stop_all_hardware()
        self.lbl_process_stage.configure(text="ALL STEPS COMPLETE")
        ctk.CTkButton(self.content_frame, text="RETURN HOME", fg_color="#2ecc71", command=self._home_screen).pack(pady=10)
    def _clear(self):
        self.content_frame.configure(fg_color="transparent") 
        for w in self.content_frame.winfo_children():
            w.destroy()

if __name__ == '__main__':
    app = CureBoxUI()
    app.mainloop()