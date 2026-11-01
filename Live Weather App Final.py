import csv

import queue

import sqlite3

import threading

import sys

import subprocess

from contextlib import closing

from datetime import datetime, timedelta

from pathlib import Path

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from matplotlib.figure import Figure

import requests

from tkinter import *

from tkinter import ttk, filedialog, messagebox

database_path = Path(__file__).with_name("weather_data.db")

def connect_database():

    return sqlite3.connect(database_path, timeout=5)

def ensure_weather_observations_table(database):

    with closing(database.cursor()) as cursor:

        cursor.execute("""

            CREATE TABLE IF NOT EXISTS weather_observations (

                city TEXT NOT NULL,

                observation_time TEXT NOT NULL,

                temperature_c REAL NOT NULL,

                humidity_percent REAL NOT NULL,

                latitude REAL NOT NULL,

                longitude REAL NOT NULL,

                PRIMARY KEY (city, observation_time)

            )

        """)

def ensure_dashboard_cities_table(database):

    with closing(database.cursor()) as cursor:

        cursor.execute("""

            CREATE TABLE IF NOT EXISTS weather_dashboard_cities (

                city TEXT PRIMARY KEY,

                latitude REAL NOT NULL,

                longitude REAL NOT NULL

            )

        """)

DEFAULT_CITY_LOCATIONS = {

    "Malegaon": (20.54966, 74.53462),

    "Mumbai": (19.07283, 72.88261),

    "Aurangabad": (19.87757, 75.34226),

    "Nashik": (19.99727, 73.79096),

    "Lucknow": (26.83928, 80.92313),

}

# ---------------------------------------------------------------------------

# Standalone background collector + Windows Task Scheduler integration

# ---------------------------------------------------------------------------

# The same file can run in two modes:

#   python weather_dashboard_hourly.py             -> dashboard + schedule setup

#   python weather_dashboard_hourly.py --background -> collect and exit

#

# The scheduled collector does not open Tkinter and works while the dashboard

# is closed. Windows and internet must be available for scheduled runs.

def collect_weather_without_dashboard():

    """Fetch current weather and save only genuinely new observations."""

    city_locations = DEFAULT_CITY_LOCATIONS.copy()

    with closing(connect_database()) as database:

        ensure_dashboard_cities_table(database)

        with closing(database.cursor()) as cursor:

            cursor.execute(

                "SELECT city, latitude, longitude FROM weather_dashboard_cities"

            )

            city_locations.update({

                city: (latitude, longitude)

                for city, latitude, longitude in cursor.fetchall()

            })

    csv_file_path = Path(__file__).resolve().with_name("weather_data.csv")

    records = []

    with requests.Session() as session:

        for city, (latitude, longitude) in city_locations.items():

            response = session.get(

                "https://api.open-meteo.com/v1/forecast",

                params={

                    "latitude": latitude,

                    "longitude": longitude,

                    "current": ["temperature_2m", "relative_humidity_2m"],

                    "timezone": "auto",

                },

                timeout=20,

            )

            response.raise_for_status()

            current = response.json()["current"]

            records.append((

                city,

                current["time"],

                current["temperature_2m"],

                current["relative_humidity_2m"],

                latitude,

                longitude,

            ))

    new_csv_rows = []

    with closing(connect_database()) as database:

        ensure_weather_observations_table(database)

        with closing(database.cursor()) as cursor:

            for record in records:

                cursor.execute("""

                    INSERT OR IGNORE INTO weather_observations

                        (city, observation_time, temperature_c, humidity_percent,

                         latitude, longitude)

                    VALUES (?, ?, ?, ?, ?, ?)

                """, record)

                if cursor.rowcount == 1:

                    new_csv_rows.append([record[0], record[1], record[2]])

        database.commit()

    if new_csv_rows:

        csv_has_data = (

            csv_file_path.exists() and csv_file_path.stat().st_size > 0

        )

        with csv_file_path.open("a", newline="", encoding="utf-8") as output:

            writer = csv.writer(output)

            if not csv_has_data:

                writer.writerow(["City", "Time", "Temperature (°C)"])

            writer.writerows(new_csv_rows)

    print(

        f"Weather check complete. New rows saved: {len(new_csv_rows)} "

        f"at {Path(__file__).resolve().parent}"

    )

def install_windows_scheduled_task():

    """Register this same file to collect weather every 60 minutes (1 hour)."""

    if sys.platform != "win32":

        print("Automatic task installation is supported on Windows only.")

        return

    script_path = str(Path(__file__).resolve())

    python_path = sys.executable

    task_name = "WeatherTemperatureCollector"

    task_action = f'"{python_path}" "{script_path}" --background'

    command = [

        "schtasks", "/Create",

        "/TN", task_name,

        "/SC", "MINUTE",

        "/MO", "60",

        "/TR", task_action,

        "/F",

    ]

    try:

        result = subprocess.run(

            command, capture_output=True, text=True, timeout=20

        )

        if result.returncode == 0:

            print(

                "Windows scheduled task is installed/updated: "

                "weather will be collected every 60 minutes (1 hour) even when "

                "the dashboard is closed."

            )

        else:

            print("Could not install the Windows scheduled task.")

            if result.stderr.strip():

                print(result.stderr.strip())

            if result.stdout.strip():

                print(result.stdout.strip())

            print(

                'You can install it manually by running this file normally '

                'from a Windows terminal with permission to create scheduled tasks.'

            )

    except (OSError, subprocess.SubprocessError) as error:

        print(f"Could not configure Windows Task Scheduler: {error}")

# Background task mode exits before the Tkinter dashboard and its startup API calls.

if __name__ == "__main__" and "--background" in sys.argv:

    try:

        collect_weather_without_dashboard()

    except Exception as error:

        print(f"Background weather collection failed: {error}", file=sys.stderr)

        raise SystemExit(1)

    raise SystemExit(0)

# Running the dashboard also installs/refreshes its hourly scheduled task.

if __name__ == "__main__":

    install_windows_scheduled_task()

def fetch_city_location(requested_city):

    search_name = "Panjim" if requested_city.casefold() == "goa" else requested_city

    response = requests.get(

        "https://geocoding-api.open-meteo.com/v1/search",

        params={

            "name": search_name,

            "count": 10,

            "language": "en",

            "format": "json",

        },

        timeout=20,

    )

    response.raise_for_status()

    matches = response.json().get("results") or []

    if not matches:

        raise ValueError(f"No city found for '{requested_city}'.")

    if requested_city.casefold() == "goa":

        location = next(

            (

                match

                for match in matches

                if match.get("name", "").casefold() == "panjim"

                and match.get("admin1", "").casefold() == "goa"

                and match.get("country") == "India"

            ),

            None,

        )

        if location is None:

            raise ValueError("Could not find Panjim in Goa, India.")

        return "Goa", location["latitude"], location["longitude"]

    location = next(

        (

            match

            for match in matches

            if match.get("name", "").casefold() == requested_city.casefold()

        ),

        matches[0],

    )

    return (

        location["name"],

        location["latitude"],

        location["longitude"],

    )

def fetch_city_weather(city, latitude, longitude):

    response = requests.get(

        "https://api.open-meteo.com/v1/forecast",

        params={

            "latitude": latitude,

            "longitude": longitude,

            "current": ["temperature_2m", "relative_humidity_2m"],

            "hourly": ["temperature_2m"],

            "daily": ["temperature_2m_max", "temperature_2m_min"],

            "forecast_days": 8,

            "forecast_hours": 24,

            "timezone": "auto",

        },

        timeout=20,

    )

    response.raise_for_status()

    data = response.json()

    current = data["current"]

    hourly = data["hourly"]

    daily = data["daily"]

    return {

        "city": city,

        "latitude": latitude,

        "longitude": longitude,

        "observation_time": current["time"],

        "temperature": current["temperature_2m"],

        "humidity": current["relative_humidity_2m"],

        "forecast_dates": daily["time"][1:8],

        "forecast_max": daily["temperature_2m_max"][1:8],

        "forecast_min": daily["temperature_2m_min"][1:8],

        "hourly_times": hourly["time"],

        "hourly_temperatures": hourly["temperature_2m"],

    }

csv_path = Path(__file__).with_name("weather_data.csv")

MAX_CITIES = 8

def load_latest_observation(city):

    with closing(connect_database()) as database:

        ensure_weather_observations_table(database)

        with closing(database.cursor()) as cursor:

            cursor.execute(

                """

                SELECT observation_time, temperature_c, humidity_percent,

                       latitude, longitude

                FROM weather_observations

                WHERE city = ?

                ORDER BY observation_time DESC

                LIMIT 1

                """,

                (city,),

            )

            return cursor.fetchone()

def cached_city_weather(city, latitude, longitude):

    observation = load_latest_observation(city)

    if observation:

        observation_time, temperature, humidity, saved_latitude, saved_longitude = observation

        latitude = saved_latitude

        longitude = saved_longitude

    else:

        observation_time = "No saved observation"

        temperature = None

        humidity = None

    return {

        "city": city,

        "latitude": latitude,

        "longitude": longitude,

        "observation_time": observation_time,

        "temperature": temperature,

        "humidity": humidity,

        "forecast_dates": [],

        "forecast_max": [],

        "forecast_min": [],

        "hourly_times": [],

        "hourly_temperatures": [],

    }

def empty_city_weather(city, latitude, longitude):

    return {

        "city": city,

        "latitude": latitude,

        "longitude": longitude,

        "observation_time": "Database unavailable",

        "temperature": None,

        "humidity": None,

        "forecast_dates": [],

        "forecast_max": [],

        "forecast_min": [],

        "hourly_times": [],

        "hourly_temperatures": [],

    }

def load_saved_city_locations():

    with closing(connect_database()) as database:

        ensure_dashboard_cities_table(database)

        with closing(database.cursor()) as cursor:

            cursor.execute(

                "SELECT city, latitude, longitude FROM weather_dashboard_cities"

            )

            return cursor.fetchall()

def save_dashboard_city(city, latitude, longitude):

    with closing(connect_database()) as database:

        ensure_dashboard_cities_table(database)

        with closing(database.cursor()) as cursor:

            cursor.execute(

                """

                INSERT INTO weather_dashboard_cities

                    (city, latitude, longitude)

                VALUES (?, ?, ?)

                ON CONFLICT(city) DO UPDATE SET

                    latitude = excluded.latitude,

                    longitude = excluded.longitude

                """,

                (city, latitude, longitude),

            )

        database.commit()

def delete_dashboard_city(city):

    with closing(connect_database()) as database:

        ensure_dashboard_cities_table(database)

        with closing(database.cursor()) as cursor:

            cursor.execute(

                "DELETE FROM weather_dashboard_cities WHERE city = ?",

                (city,),

            )

        database.commit()

def past_weather_date_range():

    today = datetime.now().date()

    return today - timedelta(days=6), today

def load_past_weather(city):

    start_date, end_date = past_weather_date_range()

    start_time = datetime.combine(start_date, datetime.min.time()).strftime(

        "%Y-%m-%dT%H:%M"

    )

    end_time = datetime.combine(

        end_date + timedelta(days=1), datetime.min.time()

    ).strftime("%Y-%m-%dT%H:%M")

    with closing(connect_database()) as database:

        ensure_weather_observations_table(database)

        with closing(database.cursor()) as cursor:

            cursor.execute(

                """

                SELECT observation_time, temperature_c

                FROM weather_observations

                WHERE city = ?

                  AND observation_time >= ?

                  AND observation_time < ?

                ORDER BY observation_time

                """,

                (city, start_time, end_time),

            )

            return cursor.fetchall()

default_city_names = ["Malegaon", "Mumbai", "Aurangabad", "Nashik", "Lucknow"]

city_weather = {}

startup_database_errors = []

for requested_city in default_city_names:

    latitude, longitude = DEFAULT_CITY_LOCATIONS[requested_city]

    if startup_database_errors:

        city_weather[requested_city] = empty_city_weather(

            requested_city, latitude, longitude

        )

    else:

        try:

            city_weather[requested_city] = cached_city_weather(

                requested_city, latitude, longitude

            )

        except sqlite3.Error as error:

            startup_database_errors.append(str(error))

            city_weather[requested_city] = empty_city_weather(

                requested_city, latitude, longitude

            )

DEFAULT_CITIES = set(city_weather)

if startup_database_errors:

    saved_city_locations = []

else:

    try:

        saved_city_locations = load_saved_city_locations()

    except sqlite3.Error as error:

        startup_database_errors.append(str(error))

        saved_city_locations = []

for city, latitude, longitude in saved_city_locations:

    if len(city_weather) >= MAX_CITIES:

        break

    if city.casefold() not in {existing.casefold() for existing in city_weather}:

        if startup_database_errors:

            city_weather[city] = empty_city_weather(city, latitude, longitude)

        else:

            try:

                city_weather[city] = cached_city_weather(city, latitude, longitude)

            except sqlite3.Error as error:

                startup_database_errors.append(str(error))

                city_weather[city] = empty_city_weather(city, latitude, longitude)

# CSV/database paths; startup itself does not save observations.

REFRESH_INTERVAL_MINUTES = 60
refresh_interval = REFRESH_INTERVAL_MINUTES * 60 * 1000

city_locations = [

    (city, data["latitude"], data["longitude"])

    for city, data in city_weather.items()

]

city_coordinates = {

    city: (latitude, longitude)

    for city, latitude, longitude in city_locations

}

def save_weather_data(weather_records, coordinates_by_city=None):

    """

    Save only new observations.

    The database primary key (city, observation_time) prevents duplicates;

    CSV rows are appended only when a new database record is inserted.

    """

    new_records = []

    coordinates_by_city = coordinates_by_city or city_coordinates

    with closing(connect_database()) as database:

        ensure_weather_observations_table(database)

        with closing(database.cursor()) as cursor:

            for city, observation_time, temperature, humidity in weather_records:

                cursor.execute(

                    """

                    INSERT OR IGNORE INTO weather_observations

                        (city, observation_time, temperature_c, humidity_percent,

                         latitude, longitude)

                    VALUES (?, ?, ?, ?, ?, ?)

                    """,

                    (

                        city,

                        observation_time,

                        temperature,

                        humidity,

                        *coordinates_by_city[city],

                    ),

                )

                if cursor.rowcount == 1:

                    new_records.append(

                        [city, observation_time, temperature]

                    )

        database.commit()

    if new_records:

        csv_exists = csv_path.exists() and csv_path.stat().st_size > 0

        with csv_path.open("a", newline="", encoding="utf-8") as csv_file:

            writer = csv.writer(csv_file)

            if not csv_exists:

                writer.writerow(["City", "Time", "Temperature (°C)"])

            writer.writerows(new_records)

# Do not save data at startup. Persistence happens during refreshes only.

# Tkinter Window

root = Tk()

BACKGROUND = "#050D18"

SURFACE = "#0D1B2B"

NAVY = "#050D18"

MUTED = "#8CA4BD"

ACCENT = "#27D8F2"

ACCENT_DARK = "#16B8D1"

TEXT = "#E6F2FF"

SUBTLE = "#1C3045"

SUCCESS = "#35D6A5"

ERROR = "#FF647C"

root.title("MIDNIGHT PRO | Weather Intelligence")

root.geometry("1366x820")

root.minsize(1080, 700)

root.state("zoomed")

root.configure(bg=BACKGROUND)

root.columnconfigure(0, weight=1)

# Whole-dashboard vertical scrolling container
window = root
app_scroll_canvas = Canvas(window, bg=BACKGROUND, highlightthickness=0, bd=0)
app_scrollbar = Scrollbar(
    window,
    orient=VERTICAL,
    command=app_scroll_canvas.yview,
    bg=BACKGROUND,
    troughcolor=SUBTLE,
    activebackground="#294158",
    highlightthickness=0,
    bd=0,
    relief=FLAT,
)
app_scroll_canvas.grid(row=0, column=0, sticky="nsew")
app_scrollbar.grid(row=0, column=1, sticky="ns")
window.columnconfigure(0, weight=1)
window.rowconfigure(0, weight=1)

app_scroll_frame = Frame(app_scroll_canvas, bg=BACKGROUND)
app_scroll_window = app_scroll_canvas.create_window(
    (0, 0), window=app_scroll_frame, anchor="nw"
)
app_scroll_canvas.configure(yscrollcommand=app_scrollbar.set)

def _update_app_scroll_region(_event=None):
    app_scroll_canvas.configure(scrollregion=app_scroll_canvas.bbox("all"))

def _fit_app_scroll_width(event):
    app_scroll_canvas.itemconfigure(app_scroll_window, width=event.width)

app_scroll_frame.bind("<Configure>", _update_app_scroll_region)
app_scroll_canvas.bind("<Configure>", _fit_app_scroll_width)

def _app_mousewheel(event):
    # Windows and macOS
    if getattr(event, "delta", 0):
        app_scroll_canvas.yview_scroll(int(-event.delta / 120), "units")
    # Linux mouse wheel
    elif getattr(event, "num", None) == 4:
        app_scroll_canvas.yview_scroll(-3, "units")
    elif getattr(event, "num", None) == 5:
        app_scroll_canvas.yview_scroll(3, "units")

window.bind_all("<MouseWheel>", _app_mousewheel)
window.bind_all("<Button-4>", _app_mousewheel)
window.bind_all("<Button-5>", _app_mousewheel)

# Build the dashboard inside the scrollable frame; keep the real Tk window
# available as `window` for window-level operations.
root = app_scroll_frame

ui_style = ttk.Style(root)

ui_style.theme_use("clam")
ui_style.configure("Treeview", background="#0D1B2B", foreground="#E6F2FF", fieldbackground="#0D1B2B", rowheight=28)
ui_style.configure("Treeview.Heading", background="#102238", foreground="#27D8F2", font=("Segoe UI", 9, "bold"))
ui_style.map("Treeview", background=[("selected", "#17314A")], foreground=[("selected", "#FFFFFF")])

ui_style.configure(

    "Weather.TNotebook",

    background=BACKGROUND,

    borderwidth=0,

    tabmargins=(0, 0, 0, 0),

)

ui_style.configure(

    "Weather.TNotebook.Tab",

    background="#102238",

    foreground=MUTED,

    padding=(18, 10),

    borderwidth=0,

    font=("Segoe UI", 9, "bold"),

)

ui_style.map(

    "Weather.TNotebook.Tab",

    background=[("selected", SURFACE), ("active", "#17314A")],

    foreground=[("selected", ACCENT_DARK), ("active", NAVY)],

)

ui_style.configure(

    "Weather.TCombobox",

    fieldbackground=SURFACE,

    background=SURFACE,

    foreground=TEXT,

    arrowcolor=ACCENT_DARK,

    bordercolor="#20384F",

    lightcolor="#20384F",

    darkcolor="#20384F",

    padding=(10, 8),

    font=("Segoe UI", 10),

)

ui_style.map(

    "Weather.TCombobox",

    fieldbackground=[("readonly", SURFACE)],

    selectbackground=[("readonly", SURFACE)],

    selectforeground=[("readonly", TEXT)],

)

header = Frame(root, bg=NAVY, padx=28, pady=10)

header.grid(row=0, column=0, sticky="ew")

header.columnconfigure(0, weight=1)

Label(

    header,

    text="◆   MIDNIGHT PRO  |  WEATHER INTELLIGENCE",

    font=("Segoe UI", 9, "bold"),

    fg="#27D8F2",

    bg=NAVY,

).grid(row=0, column=0, sticky="w")

Label(

    header,

    text="MIDNIGHT PRO",

    font=("Segoe UI", 23, "bold"),

    fg="#0D1B2B",

    bg=NAVY,

).grid(row=1, column=0, sticky="w", pady=(5, 0))

Label(

    header,

    text="WEATHER INTELLIGENCE  /  CLIENT EDITION",

    font=("Segoe UI", 10),

    fg="#8CA4BD",

    bg=NAVY,

).grid(row=2, column=0, sticky="w", pady=(4, 0))


# Live date and time in the dashboard header (uses the computer's local time).
clock_label = Label(
    header,
    text="",
    font=("Segoe UI", 10, "bold"),
    fg="#E6F2FF",
    bg=NAVY,
    anchor="e",
)
clock_label.grid(row=0, column=1, sticky="e", padx=(12, 0))

def update_dashboard_clock():
    clock_label.config(text=datetime.now().strftime("%A, %d %b %Y  |  %I:%M:%S %p"))
    root.after(1000, update_dashboard_clock)

update_dashboard_clock()

weather_controls = Frame(root, bg=BACKGROUND, padx=24, pady=8)

weather_controls.grid(row=1, column=0, sticky="ew")

weather_controls.columnconfigure(0, weight=1)

weather_status = Label(

    weather_controls,

    text="Showing saved weather where available · fetching live updates...",

    font=("Segoe UI", 9, "bold"),

    fg=MUTED,

    bg=BACKGROUND,

    anchor="w",

)

weather_status.grid(row=0, column=0, sticky="ew")

if startup_database_errors:

    weather_status.config(

        text=f"Local database unavailable: {startup_database_errors[0]}",

        fg=ERROR,

    )

SEARCH_PLACEHOLDER = "Search city (e.g. Pune)"

search_var = StringVar(value=SEARCH_PLACEHOLDER)

search_entry = Entry(

    weather_controls,

    textvariable=search_var,

    font=("Segoe UI", 10),

    relief="flat",

    bg=SURFACE,

    fg=MUTED,

    insertbackground=NAVY,

    highlightthickness=1,

    highlightbackground="#294158",

    highlightcolor=ACCENT,

    width=25,

)

search_entry.grid(row=0, column=1, padx=(14, 7), ipady=10)

add_city_button = Button(

    weather_controls,

    text="+   Add city",

    font=("Segoe UI", 9, "bold"),

    fg="#0D1B2B",

    bg=ACCENT,

    activebackground=ACCENT_DARK,

    activeforeground="#0D1B2B",

    relief="flat",

    cursor="hand2",

    padx=17,

    pady=10,

)


add_city_button.grid(row=0, column=2)
unit_button = Button(weather_controls, text="°C / °F", command=lambda: toggle_temperature_unit(),
                     font=("Segoe UI", 9, "bold"), fg="#E6F2FF", bg="#102238",
                     activebackground="#17314A", activeforeground="#27D8F2",
                     relief="flat", cursor="hand2", padx=10, pady=10)
unit_button.grid(row=0, column=3, padx=(8, 4))
compare_button = Button(weather_controls, text="Compare", command=lambda: show_comparison(),
                        font=("Segoe UI", 9, "bold"), fg="#E6F2FF", bg="#102238",
                        activebackground="#17314A", relief="flat", cursor="hand2", padx=10, pady=10)
compare_button.grid(row=0, column=4, padx=4)
pdf_button = Button(weather_controls, text="PDF report", command=lambda: export_pdf(),
                    font=("Segoe UI", 9, "bold"), fg="#E6F2FF", bg="#102238",
                    activebackground="#17314A", relief="flat", cursor="hand2", padx=10, pady=10)
pdf_button.grid(row=0, column=5, padx=4)
csv_button = Button(weather_controls, text="CSV export", command=lambda: export_csv(),
                    font=("Segoe UI", 9, "bold"), fg="#E6F2FF", bg="#102238",
                    activebackground="#17314A", relief="flat", cursor="hand2", padx=10, pady=10)
csv_button.grid(row=0, column=6, padx=4)
history_button = Button(weather_controls, text="History graph", command=lambda: show_past_forecast(),
                        font=("Segoe UI", 9, "bold"), fg="#E6F2FF", bg="#102238",
                        activebackground="#17314A", relief="flat", cursor="hand2", padx=10, pady=10)
history_button.grid(row=0, column=7, padx=4)


refresh_button = Button(

    header,

    text="↻  Refresh now",

    font=("Segoe UI", 10, "bold"),

    fg="#0D1B2B",

    bg="#87CEEB",

    activebackground="#5FB9E6",

    activeforeground="#0D1B2B",

    relief="flat",

    cursor="hand2",

    padx=20,

    pady=12,

)

refresh_button.grid(row=1, column=1, rowspan=2, sticky="e")

city_info_frame = Frame(root, bg=BACKGROUND, padx=22, pady=3)

city_info_frame.grid(row=2, column=0, sticky="ew")

city_info_frame.columnconfigure(0, weight=1)

city_card_canvas = Canvas(

    city_info_frame,

    bg=BACKGROUND,

    height=194,

    highlightthickness=0,

)

city_card_canvas.grid(row=0, column=0, sticky="ew")

city_card_frame = Frame(city_card_canvas, bg=BACKGROUND)

city_card_window = city_card_canvas.create_window(

    (0, 0), window=city_card_frame, anchor="nw"

)

city_card_scrollbar = Scrollbar(

    city_info_frame,

    orient=HORIZONTAL,

    command=city_card_canvas.xview,

    bg=BACKGROUND,

    troughcolor=SUBTLE,

    activebackground="#294158",

    highlightthickness=0,

    bd=0,

    relief=FLAT,

)

city_card_scrollbar.grid(row=1, column=0, sticky="ew", padx=5)

city_card_canvas.configure(xscrollcommand=city_card_scrollbar.set)

temperature_unit = "C"
city_labels = []

city_humidity_labels = []

city_time_labels = []

def remove_city(city):

    global city_locations

    if refresh_in_progress:

        weather_status.config(text="Wait for the current update to finish.", fg=ERROR)

        return

    if city in DEFAULT_CITIES:

        weather_status.config(text="The original dashboard cities cannot be removed.", fg=ERROR)

        return

    try:

        delete_dashboard_city(city)

    except sqlite3.Error as error:

        weather_status.config(

            text=f"Could not remove {city} from saved cities: {error}",

            fg=ERROR,

        )

        return

    city_weather.pop(city, None)

    city_coordinates.pop(city, None)

    city_locations = [location for location in city_locations if location[0] != city]

    if selected_city_var.get() == city:

        selected_city_var.set(city_locations[0][0])

    render_city_cards()

    render_overview()

    render_forecast_charts()

    update_hourly_city_list()

    weather_status.config(text=f"{city} removed from the dashboard.", fg=MUTED)

def render_city_cards():

    for child in city_card_frame.winfo_children():

        child.destroy()

    city_labels.clear()

    city_humidity_labels.clear()

    city_time_labels.clear()

    for column in range(len(city_locations)):

        city_card_frame.columnconfigure(column, weight=1, uniform="city", minsize=205)

    for index, (city, latitude, longitude) in enumerate(city_locations):

        data = city_weather[city]

        card = Frame(

            city_card_frame,

            bg=SURFACE,

            highlightbackground="#20384F",

            highlightthickness=1,

            padx=15,

            pady=11,

        )

        card.grid(

            row=0,

            column=index,

            sticky="nsew",

            padx=5,

            pady=5,

        )

        card.columnconfigure(1, weight=1)

        accent_bar = Frame(card, bg=ACCENT, width=4)

        accent_bar.grid(row=0, column=0, rowspan=6, sticky="ns", padx=(0, 12))

        accent_bar.grid_propagate(False)

        Label(

            card,

            text=city.upper(),

            font=("Segoe UI", 9, "bold"),

            fg=TEXT,

            bg=SURFACE,

        ).grid(row=0, column=1, sticky="w")

        if city not in DEFAULT_CITIES:

            Button(

                card,

                text="Remove",

                font=("Segoe UI", 8, "bold"),

                fg=MUTED,

                bg=SURFACE,

                activebackground="#3B1B2A",

                activeforeground=ERROR,

                relief="flat",

                cursor="hand2",

                command=lambda selected=city: remove_city(selected),

            ).grid(row=0, column=2, sticky="e", padx=(4, 0))

        temperature_label = Label(

            card,

            text=(

                f"{(data['temperature'] * 9 / 5 + 32 if temperature_unit == 'F' else data['temperature']):.1f}°{temperature_unit}"

                if data["temperature"] is not None

                else "--°"

            ),

            font=("Segoe UI", 30, "bold"),

            fg=ACCENT_DARK,

            bg=SURFACE,

        )

        temperature_label.grid(row=1, column=1, sticky="w", pady=(6, 0))

        Label(

            card,

            text=(

                f"{abs(latitude):.2f}° "

                f"{'N' if latitude >= 0 else 'S'}   ·   "

                f"{abs(longitude):.2f}° "

                f"{'E' if longitude >= 0 else 'W'}"

            ),

            font=("Segoe UI", 8),

            fg=MUTED,

            bg=SURFACE,

        ).grid(row=2, column=1, sticky="w", pady=(0, 8))

        Frame(card, bg=SUBTLE, height=1).grid(

            row=3,

            column=1,

            columnspan=2,

            sticky="ew",

            pady=(0, 7),

        )

        humidity_label = Label(

            card,

            text=(

                f"Humidity   {data['humidity']}%"

                if data["humidity"] is not None

                else "Humidity   --"

            ),

            font=("Segoe UI", 9, "bold"),

            fg=TEXT,

            bg=SURFACE,

        )

        humidity_label.grid(row=4, column=1, sticky="w")

        try:

            updated_text = datetime.fromisoformat(

                data["observation_time"]

            ).strftime("Updated  ·  %b %d, %H:%M")

        except ValueError:

            updated_text = f"Updated  ·  {data['observation_time']}"

        time_label = Label(

            card,

            text=updated_text,

            font=("Segoe UI", 8),

            fg=MUTED,

            bg=SURFACE,

            anchor="w",

        )

        time_label.grid(row=5, column=1, columnspan=2, sticky="w", pady=(6, 0))

        city_labels.append(temperature_label)

        city_humidity_labels.append(humidity_label)

        city_time_labels.append(time_label)

def resize_city_cards(_event=None):

    canvas_width = city_card_canvas.winfo_width()

    requested_width = max(canvas_width, city_card_frame.winfo_reqwidth())

    city_card_canvas.itemconfigure(city_card_window, width=requested_width)

    city_card_canvas.configure(scrollregion=city_card_canvas.bbox("all"))

    if requested_width > canvas_width:

        city_card_scrollbar.grid()

    else:

        city_card_scrollbar.grid_remove()

render_city_cards()

# Draw a responsive forecast panel for every city currently on the dashboard.

figure = Figure(figsize=(12, 8), dpi=100, facecolor=SURFACE)

axes = []


# ---------------------------------------------------------------------------
# MIDNIGHT PRO live overview: temperature comparison + alert sidebar
# ---------------------------------------------------------------------------
overview_frame = Frame(root, bg=BACKGROUND, padx=26, pady=8)
overview_frame.grid(row=3, column=0, sticky="nsew")
overview_frame.columnconfigure(0, weight=3)
overview_frame.columnconfigure(1, weight=1)
overview_frame.rowconfigure(0, weight=1)

overview_panel = Frame(overview_frame, bg=SURFACE, highlightbackground="#20384F", highlightthickness=1)
overview_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
overview_panel.columnconfigure(0, weight=1)
Label(overview_panel, text="TEMPERATURE OVERVIEW", bg=SURFACE, fg="#E6F2FF",
      font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w", padx=16, pady=(12, 0))
Label(overview_panel, text="Live temperature line graph • city comparison", bg=SURFACE,
      fg="#8CA4BD", font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w", padx=16, pady=(4, 2))
overview_figure = Figure(figsize=(8.6, 2.65), dpi=100, facecolor=SURFACE)
overview_axis = overview_figure.add_subplot(111)
overview_chart = FigureCanvasTkAgg(overview_figure, master=overview_panel)
overview_chart.get_tk_widget().grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 8))
overview_panel.rowconfigure(2, weight=1)

alerts_panel = Frame(overview_frame, bg=SURFACE, highlightbackground="#20384F", highlightthickness=1)
alerts_panel.grid(row=0, column=1, sticky="nsew", padx=(0, 0))
Label(alerts_panel, text="LIVE ALERTS", bg=SURFACE, fg="#E6F2FF",
      font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=14, pady=(12, 8))
alerts_list = Listbox(alerts_panel, bg="#102238", fg="#DDEBFA", relief="flat",
                      highlightthickness=0, font=("Segoe UI", 9), height=5,
                      selectbackground="#17314A", activestyle="none")
alerts_list.pack(fill="both", expand=True, padx=12, pady=(0, 10))
alert_limits = Frame(alerts_panel, bg=SURFACE)
alert_limits.pack(fill="x", padx=12, pady=(0, 8))
Label(alert_limits, text="MIN / MAX LIMITS (°C)", bg=SURFACE, fg="#8CA4BD",
      font=("Segoe UI", 8, "bold")).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 5))
min_alert_var = StringVar(value="5")
max_alert_var = StringVar(value="40")
Entry(alert_limits, textvariable=min_alert_var, width=6, bg="#102238", fg="#E6F2FF",
      insertbackground="#E6F2FF", relief="flat").grid(row=1, column=0, padx=(0, 5), ipady=5)
Label(alert_limits, text="minimum", bg=SURFACE, fg="#8CA4BD", font=("Segoe UI", 8)).grid(row=1, column=1, padx=(0, 8))
Entry(alert_limits, textvariable=max_alert_var, width=6, bg="#102238", fg="#E6F2FF",
      insertbackground="#E6F2FF", relief="flat").grid(row=1, column=2, padx=(0, 5), ipady=5)
Label(alert_limits, text="maximum", bg=SURFACE, fg="#8CA4BD", font=("Segoe UI", 8)).grid(row=1, column=3)
Button(alert_limits, text="Apply alert limits", command=lambda: apply_alert_limits(),
       bg="#102238", fg="#E6F2FF", activebackground="#17314A", relief="flat",
       font=("Segoe UI", 8, "bold"), cursor="hand2").grid(row=2, column=0, columnspan=4, sticky="ew", pady=(8, 0), ipady=5)

def render_overview():
    overview_axis.clear()
    overview_axis.set_facecolor(SURFACE)
    names, values = [], []
    alerts = []
    try:
        min_limit = float(min_alert_var.get())
        max_limit = float(max_alert_var.get())
    except (ValueError, NameError):
        min_limit, max_limit = 5.0, 40.0
    for city, _, _ in city_locations:
        data = city_weather.get(city, {})
        temperature = data.get("temperature")
        if temperature is not None:
            names.append(city)
            values.append(float(temperature))
            if temperature < min_limit:
                alerts.append(f"LOW  {city}: {temperature:.1f}°C")
            elif temperature > max_limit:
                alerts.append(f"HIGH {city}: {temperature:.1f}°C")
    if values:
        overview_axis.plot(names, values, color="#27D8F2", marker="o", markersize=7,
                           linewidth=2.8, markerfacecolor="#35D6A5",
                           markeredgecolor="#DDFBFF", markeredgewidth=1.2)
        overview_axis.fill_between(range(len(values)), values, min(values) - 2,
                                   color="#27D8F2", alpha=0.10)
        for index, value in enumerate(values):
            overview_axis.annotate(f"{value:.1f}°C", (index, value), xytext=(0, 10),
                                   textcoords="offset points", ha="center",
                                   color="#DDEBFA", fontsize=8, fontweight="bold")
        overview_axis.set_xticks(range(len(names)), names)
        overview_axis.set_ylim(min(values) - 2, max(values) + 3)
    else:
        overview_axis.text(0.5, 0.5, "Waiting for live weather data",
                           transform=overview_axis.transAxes, ha="center", color="#8CA4BD")
    overview_axis.set_ylabel("Temperature (°C)", color="#8CA4BD", fontsize=8)
    overview_axis.tick_params(axis="x", colors="#8CA4BD", labelsize=8)
    overview_axis.tick_params(axis="y", colors="#8CA4BD", labelsize=8)
    overview_axis.grid(True, color="#20384F", linewidth=0.7, alpha=0.9)
    for spine in overview_axis.spines.values():
        spine.set_color("#20384F")
    overview_figure.tight_layout(pad=1.4)
    overview_chart.draw_idle()
    alerts_list.delete(0, END)
    if alerts:
        for alert in alerts:
            alerts_list.insert(END, "⚠ " + alert)
    else:
        alerts_list.insert(END, "✓ No active alerts")

def apply_alert_limits():
    try:
        low, high = float(min_alert_var.get()), float(max_alert_var.get())
        if low >= high:
            raise ValueError
    except ValueError:
        messagebox.showerror("Invalid limits", "Enter valid limits where minimum is lower than maximum.")
        return
    render_overview()

def show_comparison():
    window = Toplevel(root)
    window.title("MIDNIGHT PRO | City comparison")
    window.configure(bg=BACKGROUND)
    window.geometry("560x420")
    Label(window, text="CITY WEATHER COMPARISON", bg=BACKGROUND, fg="#27D8F2",
          font=("Segoe UI", 15, "bold")).pack(anchor="w", padx=20, pady=18)
    table = ttk.Treeview(window, columns=("city", "temp", "humidity", "updated"),
                         show="headings", height=12)
    for col, title, width in (("city", "City", 130), ("temp", "Temperature", 100),
                              ("humidity", "Humidity", 90), ("updated", "Last update", 190)):
        table.heading(col, text=title)
        table.column(col, width=width, anchor="w")
    table.pack(fill="both", expand=True, padx=20, pady=(0, 20))
    for city, _, _ in city_locations:
        data = city_weather.get(city, {})
        table.insert("", END, values=(city,
            f"{data.get('temperature', '--')} °C",
            f"{data.get('humidity', '--')}%",
            data.get("observation_time", "--")))

def export_csv():
    destination = filedialog.asksaveasfilename(
        title="Export weather history", defaultextension=".csv",
        filetypes=[("CSV files", "*.csv")], initialfile="midnight_weather_history.csv")
    if not destination:
        return
    try:
        with closing(connect_database()) as database, closing(database.cursor()) as cursor:
            ensure_weather_observations_table(database)
            cursor.execute("""SELECT city, observation_time, temperature_c, humidity_percent,
                              latitude, longitude FROM weather_observations
                              ORDER BY observation_time DESC, city""")
            rows = cursor.fetchall()
        with open(destination, "w", newline="", encoding="utf-8") as output:
            writer = csv.writer(output)
            writer.writerow(["City", "Observation Time", "Temperature (C)", "Humidity (%)", "Latitude", "Longitude"])
            writer.writerows(rows)
        messagebox.showinfo("CSV export", f"Exported {len(rows)} observations.")
    except (OSError, sqlite3.Error) as error:
        messagebox.showerror("CSV export failed", str(error))

def export_pdf():
    destination = filedialog.asksaveasfilename(
        title="Save weather report", defaultextension=".pdf",
        filetypes=[("PDF files", "*.pdf")], initialfile="midnight_weather_report.pdf")
    if not destination:
        return
    try:
        from matplotlib.backends.backend_pdf import PdfPages
        with PdfPages(destination) as pdf:
            fig = Figure(figsize=(11.7, 8.3), facecolor="white")
            ax = fig.add_subplot(111)
            rows = [(city, city_weather.get(city, {})) for city, _, _ in city_locations]
            names = [city for city, data in rows if data.get("temperature") is not None]
            temps = [data["temperature"] for city, data in rows if data.get("temperature") is not None]
            ax.set_title("MIDNIGHT PRO | Weather Intelligence Report", fontsize=18, pad=20)
            if temps:
                ax.bar(names, temps)
                ax.set_ylabel("Temperature (°C)")
                ax.grid(axis="y", alpha=0.25)
            fig.text(0.08, 0.04, "Generated " + datetime.now().strftime("%d %b %Y, %H:%M"))
            pdf.savefig(fig, bbox_inches="tight")
            fig.clear()
            ax = fig.add_subplot(111)
            ax.axis("off")
            cell_data = [[city, str(data.get("temperature", "--")), str(data.get("humidity", "--")),
                          str(data.get("observation_time", "--"))] for city, data in rows]
            table = ax.table(cellText=cell_data, colLabels=["City", "Temp °C", "Humidity %", "Observation Time"],
                             loc="center", cellLoc="left")
            table.auto_set_font_size(False)
            table.set_fontsize(9)
            table.scale(1, 1.7)
            ax.set_title("Current conditions", fontsize=16, pad=20)
            pdf.savefig(fig, bbox_inches="tight")
        messagebox.showinfo("PDF report", "Weather report exported successfully.")
    except (OSError, sqlite3.Error, ValueError) as error:
        messagebox.showerror("PDF export failed", str(error))

def toggle_temperature_unit():
    # Weather values remain stored in Celsius; this button switches card/chart display.
    global temperature_unit
    temperature_unit = "F" if temperature_unit == "C" else "C"
    render_city_cards()
    render_overview()
    unit_button.config(text="°C / °F  (" + temperature_unit + ")")


# Forecast views

section_header = Frame(root, bg=BACKGROUND, padx=32, pady=8)

section_header.grid(row=4, column=0, sticky="new")

Label(

    section_header,

    text="Forecast outlook",

    font=("Segoe UI", 18, "bold"),

    fg=NAVY,

    bg=BACKGROUND,

).grid(row=0, column=0, sticky="w")

Label(

    section_header,

    text="Hourly conditions and a clear 7-day temperature outlook",

    font=("Segoe UI", 9),

    fg=MUTED,

    bg=BACKGROUND,

).grid(row=1, column=0, sticky="w", pady=(3, 0))

section_header.columnconfigure(0, weight=1)

forecast_navigation = Frame(section_header, bg=BACKGROUND)

forecast_navigation.grid(row=0, column=1, rowspan=2, sticky="e")

hourly_forecast_button = Button(

    forecast_navigation,

    text="Hourly",

    font=("Segoe UI", 9, "bold"),

    fg=NAVY,

    bg="#102238",

    activebackground="#17314A",

    relief="flat",

    cursor="hand2",

    padx=18,

    pady=10,

)

hourly_forecast_button.pack(side="left", padx=4)

past_forecast_button = Button(

    forecast_navigation,

    text="Past 7 days",

    font=("Segoe UI", 9, "bold"),

    fg=NAVY,

    bg="#102238",

    activebackground="#17314A",

    relief="flat",

    cursor="hand2",

    padx=18,

    pady=10,

)

past_forecast_button.pack(side="left", padx=4)

next_forecast_button = Button(

    forecast_navigation,

    text="Next 7 days",

    font=("Segoe UI", 9, "bold"),

    fg="#0D1B2B",

    bg=ACCENT,

    activebackground=ACCENT_DARK,

    activeforeground="#0D1B2B",

    relief="flat",

    cursor="hand2",

    padx=18,

    pady=10,

)

next_forecast_button.pack(side="left", padx=4)

forecast_tabs = ttk.Notebook(root, style="Weather.TNotebook")

forecast_tabs.grid(row=5, column=0, sticky="nsew", padx=28, pady=(0, 18))

root.rowconfigure(5, weight=1)

daily_tab = Frame(forecast_tabs, bg=SURFACE)

hourly_tab = Frame(forecast_tabs, bg=SURFACE)

forecast_tabs.add(hourly_tab, text="  HOURLY  ")

forecast_tabs.add(daily_tab, text="  7-DAY VIEW  ")

forecast_tabs.select(hourly_tab)

daily_toolbar = Frame(daily_tab, bg=SURFACE, padx=20, pady=12)

daily_toolbar.pack(fill="x")

daily_mode = "next"

history_status = Label(

    daily_toolbar,

    text="",

    font=("Segoe UI", 9),

    fg=MUTED,

    bg=SURFACE,

    anchor="w",

)

history_status.pack(side="left", fill="x", expand=True, padx=4)

graph_frame = Frame(daily_tab, bg=SURFACE, padx=10)

graph_frame.pack(fill="both", expand=True, pady=(0, 10))

graph_frame.rowconfigure(0, weight=1)

graph_frame.columnconfigure(0, weight=1)

graph_canvas = Canvas(graph_frame, bg=SURFACE, highlightthickness=0)

graph_canvas.grid(row=0, column=0, sticky="nsew")

graph_canvas.configure(yscrollincrement=20)

scrollbar = Scrollbar(

    graph_frame,

    orient=VERTICAL,

    command=graph_canvas.yview,

    bg=SURFACE,

    troughcolor=SUBTLE,

    activebackground="#294158",

    highlightthickness=0,

    bd=0,

    relief=FLAT,

)

scrollbar.grid(row=0, column=1, sticky="ns")

graph_canvas.configure(yscrollcommand=scrollbar.set)

chart = FigureCanvasTkAgg(figure, master=graph_canvas)

chart_widget = chart.get_tk_widget()
# Tk's embedded Matplotlib canvas defaults to white unless explicitly styled.
# Match both the widget and the figure to the dashboard's dark theme.
chart_widget.configure(
    background=SURFACE,
    highlightthickness=0,
    borderwidth=0,
)

graph_window = graph_canvas.create_window(
    (0, 0), window=chart_widget, anchor="nw"
)

def _fit_history_chart_width(event):
    # Keep the graph aligned to the visible history panel width.
    if event.width > 2:
        graph_canvas.itemconfigure(graph_window, width=event.width)
        chart_widget.configure(width=event.width)
        root.after_idle(update_scroll_region)

graph_canvas.bind("<Configure>", _fit_history_chart_width)

selected_city_var = StringVar(value=city_locations[0][0])

hourly_toolbar = Frame(hourly_tab, bg=SURFACE, padx=24, pady=16)

hourly_toolbar.pack(fill="x")

Label(

    hourly_toolbar,

    text="CITY",

    font=("Segoe UI", 9, "bold"),

    fg=MUTED,

    bg=SURFACE,

).pack(side="left", padx=(0, 12))

hourly_city_picker = ttk.Combobox(

    hourly_toolbar,

    textvariable=selected_city_var,

    values=[city for city, _, _ in city_locations],

    state="readonly",

    width=24,

    style="Weather.TCombobox",

)

hourly_city_picker.pack(side="left")

hourly_chart_heading = Label(

    hourly_toolbar,

    text="",

    font=("Segoe UI", 10, "bold"),

    fg=NAVY,

    bg=SURFACE,

)

hourly_chart_heading.pack(side="right")

hourly_graph_frame = Frame(hourly_tab, bg=SURFACE)

hourly_graph_frame.pack(fill="both", expand=True, padx=18, pady=(0, 18))

hourly_figure = Figure(

    figsize=(12, 2.8),

    dpi=100,

    facecolor=SURFACE,

)

hourly_chart = FigureCanvasTkAgg(hourly_figure, master=hourly_graph_frame)

hourly_chart_widget = hourly_chart.get_tk_widget()

hourly_chart_widget.pack(fill="both", expand=True)

def style_forecast_axis(axis):

    axis.set_facecolor(SURFACE)

    axis.set_ylabel("Temperature (°C)", color=MUTED, fontsize=9)

    axis.tick_params(axis="x", labelrotation=30, labelsize=8, colors=MUTED)

    axis.tick_params(axis="y", labelsize=8, colors=MUTED)

    axis.grid(True, color=SUBTLE, linewidth=0.8)

    for spine in ("top", "right"):

        axis.spines[spine].set_visible(False)

    for spine in ("left", "bottom"):

        axis.spines[spine].set_color("#294158")

def render_forecast_charts():

    global axes

    figure.clear()

    figure.set_facecolor(SURFACE)

    past_start_date, past_end_date = past_weather_date_range()

    past_weather = {}

    past_weather_error = None

    city_count = len(city_locations)

    row_count = (city_count + 1) // 2

    figure.set_size_inches(12, max(4.5, row_count * 3.2), forward=True)

    chart_widget.configure(height=round(figure.bbox.height))

    axes_grid = figure.subplots(row_count, 2, squeeze=False)

    axes = list(axes_grid.flatten())

    for index, (city, _, _) in enumerate(city_locations):

        axis = axes[index]

        style_forecast_axis(axis)

        if daily_mode == "past":

            try:

                observations = load_past_weather(city)

            except sqlite3.Error as error:

                observations = []

                past_weather_error = error

                history_status.config(

                    text=f"Weather history unavailable: {error}",

                    fg=ERROR,

                )

            past_weather[city] = observations

            if observations:

                times, temperatures = zip(*observations)

                plot_times = [

                    datetime.fromisoformat(observation_time)

                    for observation_time in times

                ]

                axis.plot(

                    plot_times,

                    temperatures,

                    marker="o",

                    markersize=3,

                    linewidth=2,

                    color=ACCENT,

                    label="Observed",

                )

            else:

                axis.text(

                    0.5,

                    0.5,

                    "No saved observations yet",

                    transform=axis.transAxes,

                    ha="center",

                    va="center",

                    color=MUTED,

                )

            displayed_dates = [

                past_start_date + timedelta(days=day_offset)

                for day_offset in range(7)

            ]

            axis.set_xticks([

                datetime.combine(day, datetime.min.time())

                for day in displayed_dates

            ])

            axis.set_xticklabels(

                [day.strftime("%d %b") for day in displayed_dates],

                rotation=25,

                ha="right",

            )

            axis.set_xlim(

                datetime.combine(past_start_date, datetime.min.time()),

                datetime.combine(

                    past_end_date + timedelta(days=1), datetime.min.time()

                ),

            )

            axis.set_title(

                f"{city} · Past 7 days ({past_start_date:%d %b} – "

                f"{past_end_date:%d %b})",

                loc="left",

                fontsize=12,

                fontweight="bold",

                color=NAVY,

                pad=12,

            )

        else:

            data = city_weather[city]

            if data["forecast_dates"]:

                axis.plot(

                    data["forecast_dates"],

                    data["forecast_max"],

                    marker="o",

                    markersize=4,

                    linewidth=2.2,

                    color=ACCENT,

                    label="High",

                )

                axis.plot(

                    data["forecast_dates"],

                    data["forecast_min"],

                    marker="o",

                    markersize=4,

                    linewidth=2.2,

                    color="#FFB86B",

                    label="Low",

                )

            else:

                axis.text(

                    0.5,

                    0.5,

                    "Forecast unavailable offline",

                    transform=axis.transAxes,

                    ha="center",

                    va="center",

                    color=MUTED,

                )

            axis.set_title(

                f"{city} · Next 7 days",

                loc="left",

                fontsize=12,

                fontweight="bold",

                color=NAVY,

                pad=12,

            )

        if axis.lines:

            axis.legend(frameon=False, loc="upper right", fontsize=8, ncol=2)

    for axis in axes[city_count:]:

        axis.set_visible(False)

    figure.tight_layout(pad=2.5)
    # Keep the Matplotlib figure background dark, including empty areas around
    # the axes, and redraw after the number of city rows changes.
    figure.set_facecolor(SURFACE)
    chart_widget.configure(background=SURFACE)
    chart.draw()
    chart_widget.update_idletasks()
    update_scroll_region()

    if daily_mode == "past":

        if past_weather_error is None:

            saved_count = sum(bool(rows) for rows in past_weather.values())

            history_status.config(

                text=(

                    f"{past_start_date:%d %b} – {past_end_date:%d %b} · "

                    f"Recorded data available for {saved_count} of "

                    f"{city_count} cities. History starts when collection begins. "

                    "Scroll down for remaining city charts."

                ),

                fg=MUTED,

            )

        past_forecast_button.config(bg=ACCENT, fg="#0D1B2B")

        next_forecast_button.config(bg="#102238", fg=NAVY)

        hourly_forecast_button.config(bg="#102238", fg=NAVY)

    else:

        history_status.config(

            text=(

                "Forecast for the next 7 days · "

                "Scroll down for remaining city charts."

            ),

            fg=MUTED,

        )

        past_forecast_button.config(bg="#102238", fg=NAVY)

        next_forecast_button.config(bg=ACCENT, fg="#0D1B2B")

        hourly_forecast_button.config(bg="#102238", fg=NAVY)

def show_past_forecast():

    """Switch to the history graph and render it immediately."""
    global daily_mode

    daily_mode = "past"
    try:
        # Switch to the graph tab first, then force Tkinter to lay it out
        # before drawing so the graph is visible immediately after the click.
        forecast_tabs.select(daily_tab)
        root.update_idletasks()
        render_forecast_charts()
        root.update_idletasks()
        update_scroll_region()
        graph_canvas.yview_moveto(0)
        history_status.config(
            text="Historical temperature graph · past 7 days",
            fg=ACCENT
        )
    except Exception as error:
        history_status.config(
            text=f"History graph error: {error}",
            fg=ERROR
        )
        messagebox.showerror(
            "History graph error",
            f"Could not open the history graph.\\n\\n{error}"
        )


def render_history_graph_safely():
    """Render historical charts and show any errors instead of silently failing."""
    try:
        render_forecast_charts()
        forecast_tabs.select(daily_tab)
        history_status.config(
            text="Historical temperature graph · past 7 days",
            fg=ACCENT
        )
    except Exception as error:
        history_status.config(
            text=f"History graph error: {error}",
            fg=ERROR
        )
        messagebox.showerror(
            "History graph error",
            f"The history graph could not be rendered.\\n\\n{error}"
        )

def show_next_forecast():

    global daily_mode

    daily_mode = "next"

    forecast_tabs.select(daily_tab)

    render_forecast_charts()

def show_hourly_forecast():

    forecast_tabs.select(hourly_tab)

    hourly_forecast_button.config(bg=ACCENT, fg="#0D1B2B")

    past_forecast_button.config(bg="#102238", fg=NAVY)

    next_forecast_button.config(bg="#102238", fg=NAVY)

    render_hourly_forecast()

def render_hourly_forecast(_event=None):

    city = selected_city_var.get()

    data = city_weather.get(city)

    if not data:

        return

    hourly_figure.clear()

    hourly_figure.set_facecolor(SURFACE)

    axis = hourly_figure.add_subplot(111)

    style_forecast_axis(axis)

    axis.set_ylabel("°C", rotation=0, labelpad=12)

    hourly_chart_heading.config(text=f"{city}  ·  NEXT 24 HOURS")

    times = data["hourly_times"]

    temperatures = data["hourly_temperatures"]

    if times and temperatures:

        axis.plot(

            range(len(times)),

            temperatures,

            color=ACCENT,

            linewidth=2.8,

            marker="o",

            markersize=4,

        )

        axis.fill_between(range(len(times)), temperatures, color=ACCENT, alpha=0.12)

        tick_positions = list(range(0, len(times), 4))

        axis.set_xticks(tick_positions)

        axis.set_xticklabels(

            [times[index][11:16] for index in tick_positions],

            rotation=0,

        )

    else:

        axis.set_xticks([])

        axis.set_yticks([])

        axis.text(

            0.5,

            0.5,

            "Hourly forecast unavailable offline",

            transform=axis.transAxes,

            ha="center",

            va="center",

            color=MUTED,

        )

    hourly_figure.subplots_adjust(left=0.06, right=0.99, top=0.93, bottom=0.35)

    hourly_chart.draw()

def resize_hourly_forecast(event):

    if event.width < 2 or event.height < 2:

        return

    figure_size = (

        event.width / hourly_figure.dpi,

        event.height / hourly_figure.dpi,

    )

    current_size = hourly_figure.get_size_inches()

    if any(

        abs(current - new) > 0.02

        for current, new in zip(current_size, figure_size)

    ):

        hourly_figure.set_size_inches(*figure_size, forward=True)

        hourly_chart.draw_idle()

def update_hourly_city_list():

    cities = [city for city, _, _ in city_locations]

    hourly_city_picker.configure(values=cities)

    if selected_city_var.get() not in cities:

        selected_city_var.set(cities[0])

    render_hourly_forecast()

def update_scroll_region(_event=None):

    graph_canvas.itemconfigure(

        graph_window,

        height=chart_widget.winfo_reqheight(),

    )

    bounds = graph_canvas.bbox(graph_window)

    if bounds:

        graph_canvas.configure(scrollregion=bounds)

def resize_graph(event):

    graph_canvas.itemconfigure(

        graph_window,

        width=event.width,

        height=chart_widget.winfo_reqheight(),

    )

    root.after_idle(update_scroll_region)

def scroll_graph(event):

    graph_canvas.yview_scroll(int(-event.delta / 120) * 3, "units")

def scroll_active_forecast(event):

    if forecast_tabs.select() != str(hourly_tab):

        scroll_graph(event)

render_forecast_charts()

show_hourly_forecast()

hourly_city_picker.bind("<<ComboboxSelected>>", render_hourly_forecast)

hourly_graph_frame.bind("<Configure>", resize_hourly_forecast)

refresh_queue = queue.Queue()

refresh_in_progress = False

def fetch_weather_updates(locations):

    weather_updates = []

    for city, latitude, longitude in locations:

        weather_updates.append(fetch_city_weather(city, latitude, longitude))

    return weather_updates

def add_city_in_background(requested_city):

    try:

        city, latitude, longitude = fetch_city_location(requested_city)

        weather = fetch_city_weather(city, latitude, longitude)

        refresh_queue.put(("add_success", weather))

    except (

        requests.RequestException,

        sqlite3.Error,

        OSError,

        KeyError,

        TypeError,

        ValueError,

    ) as error:

        refresh_queue.put(("error", str(error)))

def refresh_weather_in_background(locations):

    try:

        updates = fetch_weather_updates(locations)

        save_weather_data([

            (

                update["city"],

                update["observation_time"],

                update["temperature"],

                update["humidity"],

            )

            for update in updates

        ])

        refresh_queue.put(("success", updates))

    except (

        requests.RequestException,

        sqlite3.Error,

        OSError,

        KeyError,

        TypeError,

        ValueError,

    ) as error:

        refresh_queue.put(("error", str(error)))

def start_weather_refresh():

    global refresh_in_progress

    if refresh_in_progress:

        return

    refresh_in_progress = True

    add_city_button.config(state=DISABLED)

    refresh_button.config(state=DISABLED)

    weather_status.config(

        text="Refreshing weather data for all dashboard cities...",

        fg=MUTED,

    )

    locations = list(city_locations)

    refresh_thread = threading.Thread(

        target=refresh_weather_in_background,

        args=(locations,),

        daemon=True,

    )

    refresh_thread.start()

def start_city_search():

    global refresh_in_progress

    requested_city = search_var.get().strip()

    if not requested_city or requested_city == SEARCH_PLACEHOLDER:

        weather_status.config(text="Enter a city name to search.", fg=ERROR)

        search_entry.focus_set()

        return

    if refresh_in_progress:

        return

    if len(city_locations) >= MAX_CITIES:

        weather_status.config(

            text=f"Dashboard limit reached ({MAX_CITIES} cities). Remove a city first.",

            fg=ERROR,

        )

        return

    if any(city.casefold() == requested_city.casefold() for city, _, _ in city_locations):

        weather_status.config(text=f"{requested_city} is already on the dashboard.", fg=ERROR)

        return

    refresh_in_progress = True

    add_city_button.config(state=DISABLED)

    refresh_button.config(state=DISABLED)

    search_entry.config(state=DISABLED)

    weather_status.config(text=f"Searching weather for {requested_city}...", fg=MUTED)

    threading.Thread(

        target=add_city_in_background,

        args=(requested_city,),

        daemon=True,

    ).start()

def process_refresh_queue():

    try:

        result, data = refresh_queue.get_nowait()

    except queue.Empty:

        root.after(250, process_refresh_queue)

        return

    global refresh_in_progress

    refresh_in_progress = False

    add_city_button.config(state=NORMAL)

    refresh_button.config(state=NORMAL)

    search_entry.config(state=NORMAL)

    if result == "add_success":

        city = data["city"]

        if any(existing.casefold() == city.casefold() for existing, _, _ in city_locations):

            weather_status.config(text=f"{city} is already on the dashboard.", fg=ERROR)

        elif len(city_locations) >= MAX_CITIES:

            weather_status.config(

                text=f"Dashboard limit reached ({MAX_CITIES} cities).",

                fg=ERROR,

            )

        else:

            try:

                save_dashboard_city(city, data["latitude"], data["longitude"])

                save_weather_data(

                    [(

                        city,

                        data["observation_time"],

                        data["temperature"],

                        data["humidity"],

                    )],

                    {city: (data["latitude"], data["longitude"])},

                )

            except sqlite3.Error as error:

                weather_status.config(

                    text=f"Could not save {city} and its first reading: {error}",

                    fg=ERROR,

                )

            else:

                city_weather[city] = data

                city_coordinates[city] = (data["latitude"], data["longitude"])

                city_locations.append((city, data["latitude"], data["longitude"]))

                search_var.set(SEARCH_PLACEHOLDER)

                search_entry.config(fg=MUTED)

                selected_city_var.set(city)

                render_city_cards()

                render_overview()

                render_forecast_charts()

                update_hourly_city_list()

                weather_status.config(

                    text=f"{city} added · hourly and 7-day forecasts are ready.",

                    fg=SUCCESS,

                )

    elif result == "success":

        for update in data:

            city_weather[update["city"]] = update

        render_city_cards()

        render_overview()

        render_forecast_charts()

        render_hourly_forecast()

        weather_status.config(

            text=f"Weather updated at {data[0]['observation_time']}. "

            "Next update in 1 hour.",

            fg=SUCCESS,

        )

    else:

        weather_status.config(text=f"Weather update failed: {data}", fg=ERROR)

    root.after(250, process_refresh_queue)

def automatic_weather_refresh():

    # Starts automatically without requiring the Update Now button.

    start_weather_refresh()

    root.after(refresh_interval, automatic_weather_refresh)

def schedule_daily_history_refresh():

    next_midnight = datetime.combine(

        datetime.now().date() + timedelta(days=1),

        datetime.min.time(),

    )

    delay_ms = max(

        1000,

        int((next_midnight - datetime.now()).total_seconds() * 1000) + 1000,

    )

    root.after(delay_ms, refresh_history_at_midnight)

def refresh_history_at_midnight():

    if daily_mode == "past":

        render_forecast_charts()

    schedule_daily_history_refresh()

refresh_button.config(command=start_weather_refresh)

add_city_button.config(command=start_city_search)

hourly_forecast_button.config(command=show_hourly_forecast)

past_forecast_button.config(command=show_past_forecast)

next_forecast_button.config(command=show_next_forecast)

search_entry.bind("<Return>", lambda _event: start_city_search())

def clear_search_placeholder(_event=None):

    if search_var.get() == SEARCH_PLACEHOLDER:

        search_var.set("")

        search_entry.config(fg=NAVY)

def restore_search_placeholder(_event=None):

    if not search_var.get().strip():

        search_var.set(SEARCH_PLACEHOLDER)

        search_entry.config(fg=MUTED)

search_entry.bind("<FocusIn>", clear_search_placeholder)

search_entry.bind("<FocusOut>", restore_search_placeholder)

chart_widget.bind("<Configure>", update_scroll_region)

graph_canvas.bind("<Configure>", resize_graph)

city_card_frame.bind("<Configure>", resize_city_cards)

city_card_canvas.bind("<Configure>", resize_city_cards)

graph_canvas.bind_all("<MouseWheel>", scroll_active_forecast)

forecast_tabs.bind(

    "<<NotebookTabChanged>>",

    lambda _event: (

        render_hourly_forecast()

        if forecast_tabs.select() == str(hourly_tab)

        else render_forecast_charts()

    ),

)

root.after_idle(lambda: graph_canvas.configure(scrollregion=graph_canvas.bbox("all")))

root.after_idle(resize_city_cards)
root.after_idle(render_overview)

root.after(100, start_weather_refresh)

root.after(refresh_interval, automatic_weather_refresh)

schedule_daily_history_refresh()

root.after(250, process_refresh_queue)

window.mainloop()
