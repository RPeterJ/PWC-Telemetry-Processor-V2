#C:\Users\Richard\PycharmProjects\YamahaSpeed2RPM\.venv\Scripts\python.exe" -m pip uninstall typing
import tkinter as tk
from tkinter import filedialog, messagebox
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.scrolled import ScrolledFrame
import pandas as pd
import numpy as np
from scipy.interpolate import interp1d
import os
import json
import threading
from datetime import datetime

# --- File Parsing Functions ---
try:
    import fitparse
except ImportError:
    fitparse = None
try:
    from gpmf import GPMF_parser
except ImportError:
    GPMF_parser = None
try:
    import gpxpy
    import gpxpy.gpx
except ImportError:
    gpxpy = None


def parse_fit_file(file_path):
    if not fitparse: raise ImportError("'fitparse' library not found. Please run: pip install fitparse")
    fitfile = fitparse.FitFile(file_path)
    records = list(fitfile.get_messages('record'))
    if not records: raise ValueError("No 'record' messages found in .fit file.")
    timestamps = [r.get_value('timestamp') for r in records if
                  r.get_value('timestamp') and r.get_value('speed') is not None]
    speeds_ms = [r.get_value('speed') for r in records if r.get_value('timestamp') and r.get_value('speed') is not None]
    if not timestamps: raise ValueError("Could not extract valid data from .fit file.")
    df = pd.DataFrame({'timestamp': pd.to_datetime(timestamps), 'speed_ms': speeds_ms})
    df['speed_kmh'] = df['speed_ms'] * 3.6
    return df[['timestamp', 'speed_kmh']]


def parse_gopro_file(file_path):
    if not GPMF_parser: raise ImportError("'gpmf-parser' library not found. Please run: pip install gpmf-parser")
    parser = GPMF_parser(file_path)
    stream = parser.get_streams().get('GPS5')
    if not stream or not stream.data: raise ValueError("No GPS5 stream found. GPS may have been off.")
    df = stream.to_dataframe()
    timestamps = pd.to_datetime(parser.get_timestamps('GPS'), unit='s')
    df.index = timestamps
    df.reset_index(inplace=True)
    df.rename(columns={'index': 'timestamp', 'speed-2d': 'speed_ms'}, inplace=True)
    df['speed_kmh'] = df['speed_ms'] * 3.6
    return df[['timestamp', 'speed_kmh']]


def parse_gpx_file(file_path):
    if not gpxpy: raise ImportError("'gpxpy' library not found. Please run: pip install gpxpy")
    timestamps, speeds_ms = [], []
    with open(file_path, 'r', encoding='utf-8') as gpx_file:
        gpx = gpxpy.parse(gpx_file)
    for track in gpx.tracks:
        for segment in track.segments:
            if not segment.points: continue
            segment.points[0].speed = 0.0
            for i in range(1, len(segment.points)):
                segment.points[i].speed = segment.points[i].speed_between(segment.points[i - 1])
            for point in segment.points:
                if point.time and point.speed is not None:
                    ts = point.time if point.time.tzinfo else point.time.replace(
                        tzinfo=datetime.now().astimezone().tzinfo)
                    timestamps.append(ts)
                    speeds_ms.append(point.speed)
    if not timestamps: raise ValueError("Could not extract valid timestamp and speed data from .gpx file.")
    df = pd.DataFrame({'timestamp': pd.to_datetime(timestamps, utc=True), 'speed_ms': speeds_ms})
    df['speed_kmh'] = df['speed_ms'] * 3.6
    return df[['timestamp', 'speed_kmh']]


# --- Calculation Engine ---
def calculate_telemetry(data_df, ride_conditions, profile_data):
    """Calculates telemetry using a dynamic profile for the models."""
    rider_weight_kg, engine_size, fuel_load, drive_mode, water_condition = ride_conditions
    rpm_model = profile_data['rpm_model']
    fuel_model = profile_data['fuel_model']

    speed_data_mph = np.array(rpm_model['speed_mph'])
    rpm_data = np.array(rpm_model['rpm'], dtype=float)
    fuel_rpm_data = np.array(fuel_model['rpm'])
    fuel_lph_data = np.array(fuel_model['lph'])

    engine_factor = 1.0 if engine_size == '1.8L' else 1.05
    weight_factor = 1.0 + (rider_weight_kg - 80) * 0.001
    fuel_factors = {'full': 1.02, 'half': 1.01, 'low': 1.0}
    water_factor = 1.03 if water_condition.lower() == 'rough' else 1.0
    drive_factors = {'normal': 1.0, 'l-mode': 0.85, 'no-wake': 0.3}

    total_factor = engine_factor * weight_factor * fuel_factors[fuel_load.lower()] * water_factor * drive_factors[
        drive_mode.lower()]
    adjusted_rpm_data = rpm_data * total_factor

    rpm_interp_func = interp1d(speed_data_mph, adjusted_rpm_data, kind='linear', fill_value="extrapolate")
    fuel_interp_func = interp1d(fuel_rpm_data, fuel_lph_data, kind='linear', fill_value="extrapolate")

    telemetry_df = data_df.copy()
    telemetry_df['speed_mph'] = telemetry_df['speed_kmh'] * 0.621371
    telemetry_df['rpm'] = rpm_interp_func(telemetry_df['speed_mph']).round().astype(int)
    telemetry_df['rpm'] = telemetry_df['rpm'].clip(lower=rpm_data.min(), upper=rpm_data.max() * total_factor)
    telemetry_df['fuel_consumption_lph'] = fuel_interp_func(telemetry_df['rpm'])
    telemetry_df['fuel_consumption_lph'] = telemetry_df['fuel_consumption_lph'].clip(lower=0)

    telemetry_df['time_delta_s'] = telemetry_df['timestamp'].diff().dt.total_seconds().fillna(0)
    fuel_used_in_interval = telemetry_df['fuel_consumption_lph'] * (telemetry_df['time_delta_s'] / 3600)
    telemetry_df['cumulative_fuel_used_l'] = fuel_used_in_interval.cumsum()

    output_columns = {
        'timestamp': 'date', 'speed_kmh': 'Speed (km/h)', 'rpm': 'Engine RPM (rpm)',
        'fuel_consumption_lph': 'Fuel Rate (L/h)', 'cumulative_fuel_used_l': 'Fuel Used (L)'
    }
    return telemetry_df[output_columns.keys()].rename(columns=output_columns)


# --- Profile Manager Window ("Training" Interface) ---
class ProfileManager(tk.Toplevel):
    def __init__(self, parent, profiles, callback):
        super().__init__(parent)
        self.title("Profile Manager")
        self.geometry("800x700")
        self.transient(parent)
        self.grab_set()

        self.profiles = profiles
        self.callback = callback
        self.current_profile_name = tk.StringVar(value=list(profiles.keys())[0])
        self.entry_widgets = {'rpm_model': [], 'fuel_model': []}

        self._create_widgets()
        self.load_profile_data()

    def _create_widgets(self):
        top_frame = ttk.Frame(self, padding=10)
        top_frame.pack(fill=X)
        ttk.Label(top_frame, text="Select Profile:").pack(side=LEFT, padx=5)
        profile_menu = ttk.Combobox(top_frame, textvariable=self.current_profile_name,
                                    values=list(self.profiles.keys()), state="readonly")
        profile_menu.pack(side=LEFT, padx=5)
        profile_menu.bind("<<ComboboxSelected>>", lambda e: self.load_profile_data())

        scroll_frame = ScrolledFrame(self, autohide=True)
        scroll_frame.pack(fill=BOTH, expand=YES, padx=10, pady=10)

        rpm_frame = ttk.Labelframe(scroll_frame, text="RPM Model (Speed vs RPM)", padding=15)
        rpm_frame.pack(fill=X, pady=10)
        self.create_model_grid(rpm_frame, 'rpm_model', ('Speed (mph)', 'RPM'))

        fuel_frame = ttk.Labelframe(scroll_frame, text="Fuel Consumption Model (RPM vs L/h)", padding=15)
        fuel_frame.pack(fill=X, pady=10)
        self.create_model_grid(fuel_frame, 'fuel_model', ('RPM', 'Liters/Hour'))

        save_button = ttk.Button(self, text="Save All Profiles and Close", command=self.save_and_close,
                                 bootstyle="success")
        save_button.pack(pady=10)

    def create_model_grid(self, parent_frame, model_key, headers):
        ttk.Label(parent_frame, text=headers[0], font="-weight bold").grid(row=0, column=0, padx=5)
        ttk.Label(parent_frame, text=headers[1], font="-weight bold").grid(row=0, column=1, padx=5)
        self.entry_widgets[model_key] = []

        profile_data = self.profiles[self.current_profile_name.get()][model_key]
        num_points = len(profile_data[list(profile_data.keys())[0]])

        for i in range(num_points):
            entry1 = ttk.Entry(parent_frame, width=10)
            entry1.grid(row=i + 1, column=0, padx=5, pady=2)
            entry2 = ttk.Entry(parent_frame, width=10)
            entry2.grid(row=i + 1, column=1, padx=5, pady=2)
            self.entry_widgets[model_key].append((entry1, entry2))

    def load_profile_data(self):
        profile_name = self.current_profile_name.get()
        profile = self.profiles[profile_name]

        for model_key, entries in self.entry_widgets.items():
            model_data = profile[model_key]
            key1, key2 = model_data.keys()
            for i, (val1, val2) in enumerate(zip(model_data[key1], model_data[key2])):
                entries[i][0].delete(0, END)
                entries[i][0].insert(0, str(val1))
                entries[i][1].delete(0, END)
                entries[i][1].insert(0, str(val2))

    def save_and_close(self):
        try:
            profile_name = self.current_profile_name.get()
            for model_key, entries in self.entry_widgets.items():
                key1, key2 = self.profiles[profile_name][model_key].keys()
                self.profiles[profile_name][model_key][key1] = [float(e[0].get()) for e in entries]
                self.profiles[profile_name][model_key][key2] = [float(e[1].get()) for e in entries]

            with open("profiles.json", "w") as f:
                json.dump(self.profiles, f, indent=4)

            messagebox.showinfo("Success", "Profiles saved successfully!")
            self.callback(self.profiles)
            self.destroy()
        except ValueError as e:
            messagebox.showerror("Invalid Input", f"Please ensure all values are valid numbers.\n\nError: {e}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save profiles.\n\n{e}")


# --- Main Application GUI ---
class TelemetryApp:
    def __init__(self, root):
        self.root = root
        self.root.title("PWC Telemetry Processor V2")
        self.root.geometry("600x700")

        self.profiles = self.load_profiles()

        self.input_file_path = tk.StringVar(value="No file selected...")
        self.rider_weight = tk.DoubleVar(value=77.0)
        self.engine_size = tk.StringVar(value="1.8L")
        self.fuel_load = tk.StringVar(value="full")
        self.drive_mode = tk.StringVar(value="normal")
        self.water_condition = tk.StringVar(value="calm")
        self.selected_profile = tk.StringVar(value=list(self.profiles.keys())[0])

        self._create_widgets()

    def load_profiles(self):
        try:
            with open("profiles.json", "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            messagebox.showerror("Profile Error", "Could not load 'profiles.json'. Make sure it exists and is valid.")
            return {"default": {"rpm_model": {}, "fuel_model": {}}}

    def update_profiles(self, new_profiles):
        self.profiles = new_profiles
        self.profile_menu['values'] = list(self.profiles.keys())
        self.log("Profiles have been updated.")

    def _create_widgets(self):
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.pack(fill=BOTH, expand=YES)

        top_frame = ttk.Labelframe(main_frame, text="Setup", padding="10")
        top_frame.pack(fill=X, pady=10)

        file_label = ttk.Label(top_frame, textvariable=self.input_file_path, wraplength=450)
        file_label.grid(row=0, column=0, columnspan=2, sticky=EW, pady=5)
        browse_btn = ttk.Button(top_frame, text="Browse...", command=self.browse_file, bootstyle="info")
        browse_btn.grid(row=0, column=2, padx=5)

        ttk.Label(top_frame, text="Jet Ski Profile:").grid(row=1, column=0, sticky=W, pady=5)
        self.profile_menu = ttk.Combobox(top_frame, textvariable=self.selected_profile,
                                         values=list(self.profiles.keys()), state="readonly")
        self.profile_menu.grid(row=1, column=1, sticky=EW, pady=5)
        manage_btn = ttk.Button(top_frame, text="Manage Profiles...", command=self.open_profile_manager,
                                bootstyle="secondary")
        manage_btn.grid(row=1, column=2, padx=5)
        top_frame.columnconfigure(1, weight=1)

        conditions_frame = ttk.Labelframe(main_frame, text="Ride Conditions", padding="15")
        conditions_frame.pack(fill=X, pady=10)
        conditions_frame.columnconfigure(1, weight=1)

        fields = {
            "Rider Weight (kg):": (self.rider_weight, "Entry", None),
            "Engine Size:": (self.engine_size, "Combobox", ["1.8L", "1.9L"]),
            "Fuel Load:": (self.fuel_load, "Combobox", ["full", "half", "low"]),
            "Drive Mode:": (self.drive_mode, "Combobox", ["normal", "l-mode", "no-wake"]),
            "Water Condition:": (self.water_condition, "Combobox", ["calm", "rough"])
        }

        for i, (label, (var, widget_type, values)) in enumerate(fields.items()):
            ttk.Label(conditions_frame, text=label).grid(row=i, column=0, padx=5, pady=5, sticky=W)
            widget = ttk.Entry(conditions_frame, textvariable=var,
                               width=15) if widget_type == "Entry" else ttk.Combobox(conditions_frame, textvariable=var,
                                                                                     values=values, state="readonly",
                                                                                     width=13)
            widget.grid(row=i, column=1, padx=5, pady=5, sticky=W)

        ttk.Button(main_frame, text="Generate Telemetry Data", command=self.run_processing_thread,
                   bootstyle="success-lg").pack(pady=20, fill=X)

        log_frame = ttk.Labelframe(main_frame, text="Status Log", padding="10")
        log_frame.pack(fill=BOTH, expand=YES)

        self.log_text = tk.Text(log_frame, height=10, state="disabled", wrap="word", bg="#333", fg="#ddd",
                                relief="flat")
        scrollbar = ttk.Scrollbar(log_frame, orient=VERTICAL, command=self.log_text.yview)
        self.log_text['yscrollcommand'] = scrollbar.set
        scrollbar.pack(side=RIGHT, fill=Y)
        self.log_text.pack(side=LEFT, fill=BOTH, expand=YES)

    def open_profile_manager(self):
        ProfileManager(self.root, self.profiles, self.update_profiles)

    def log(self, message):
        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, f"{datetime.now().strftime('%H:%M:%S')} - {message}\n")
        self.log_text.config(state="disabled")
        self.log_text.see(tk.END)
        self.root.update_idletasks()

    def browse_file(self):
        # Issues with .fit and .mp4 parsing
        #file_path = filedialog.askopenfilename(title="Select GPX Activity File",filetypes=(("GPS Files", "*.gpx *.fit *.mp4"), ("All files", "*.*")))
        file_path = filedialog.askopenfilename(title="Select GPX Activity File",
                                               filetypes=(("GPS Files", "*.gpx"), ("All files", "*.*")))
        if file_path:
            self.input_file_path.set(file_path)
            self.log(f"Selected input file: {os.path.basename(file_path)}")

    def run_processing_thread(self):
        thread = threading.Thread(target=self.process_file)
        thread.daemon = True
        thread.start()

    def process_file(self):
        input_path = self.input_file_path.get()
        if not os.path.exists(input_path):
            self.log("ERROR: Please select a valid input file first.")
            messagebox.showerror("Error", "No input file selected.")
            return

        default_name = f"{os.path.splitext(os.path.basename(input_path))[0]}_telemetry.csv"
        output_path = filedialog.asksaveasfilename(
            title="Save Telemetry As",
            initialfile=default_name,
            defaultextension=".csv",
            filetypes=(("CSV files", "*.csv"), ("Excel files", "*.xlsx"))
        )
        if not output_path:
            self.log("Save operation cancelled by user.")
            return

        try:
            self.log("Starting telemetry generation...")
            self.log(f"Parsing {os.path.basename(input_path)}...")
            file_ext = os.path.splitext(input_path)[1].lower()
            parser_map = {'.fit': parse_fit_file, '.gpx': parse_gpx_file, '.mp4': parse_gopro_file}

            if file_ext not in parser_map or parser_map[file_ext] is None:
                raise ValueError(f"Unsupported file type or missing parser library for '{file_ext}'")

            raw_df = parser_map[file_ext](input_path)
            self.log(f"Successfully parsed {len(raw_df)} data points.")

            profile_name = self.selected_profile.get()
            selected_profile_data = self.profiles.get(profile_name)
            if not selected_profile_data:
                raise ValueError(f"Profile '{profile_name}' not found!")
            self.log(f"Using profile: {profile_name}")

            ride_conditions = (
                self.rider_weight.get(), self.engine_size.get(),
                self.fuel_load.get(), self.drive_mode.get(), self.water_condition.get()
            )

            self.log("Calculating telemetry with selected profile...")
            telemetry_df = calculate_telemetry(raw_df, ride_conditions, selected_profile_data)

            if output_path.endswith('.csv'):
                telemetry_df.to_csv(output_path, index=False, date_format='%Y-%m-%dT%H:%M:%S.%fZ')
            else:
                telemetry_df.to_excel(output_path, index=False, engine='openpyxl')

            self.log(f"SUCCESS! Telemetry data saved to:\n{output_path}")
            messagebox.showinfo("Success", f"Telemetry file generated successfully!\n\nSaved at: {output_path}")

        except Exception as e:
            self.log(f"ERROR: {e}")
            messagebox.showerror("Processing Error", f"An error occurred:\n\n{e}")


if __name__ == "__main__":
    root = ttk.Window(themename="darkly")
    app = TelemetryApp(root)
    root.mainloop()
