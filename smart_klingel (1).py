# -*- coding: utf-8 -*-
import tkinter as tk
import datetime
import requests
import threading
import os
import json
from flask import Flask, render_template_string, request, redirect, url_for, send_file
from gpiozero import LED, TonalBuzzer
from time import sleep
from collections import Counter

# --- HARDWARE SETUP ---
led_feedback = LED(17)
led_door = LED(27)
buzzer = TonalBuzzer(18)

# --- KONFIGURATION ---
LOG_FILE = "klingel_log.txt"
CODES_FILE = "codes.json"
NTFY_TOPIC = "dein-name-hier"   # <--- ANPASSEN!

# Oeffnungszeiten Text (fuer Anzeige)
OPENING_TEXT = "Mo - Fr: 08:00 - 17:00\nSa: 09:00 - 13:00"

# --- DESIGN KONFIGURATION ---
THEME_DAY = {
    "bg": "#ecf0f1", "fg": "#2c3e50", 
    "btn_bg": "#bdc3c7", "btn_fg": "#2c3e50", "bell_bg": "#e74c3c"
}
THEME_NIGHT = {
    "bg": "#2c3e50", "fg": "#ecf0f1", 
    "btn_bg": "#34495e", "btn_fg": "#ecf0f1", "bell_bg": "#c0392b"
}

current_theme = THEME_DAY
is_night_mode = False
reset_timer = None

# --- LOGIK: IST GEOEFFNET? ---
def check_is_open():
    """Prueft ob wir gerade Oeffnungszeit haben"""
    now = datetime.datetime.now()
    weekday = now.weekday() # 0=Montag, 6=Sonntag
    hour = now.hour
    
    # Montag (0) bis Freitag (4): 8 bis 17 Uhr
    if 0 <= weekday <= 4:
        return 8 <= hour < 17
    # Samstag (5): 9 bis 13 Uhr
    elif weekday == 5:
        return 9 <= hour < 13
    
    return False # Sonst geschlossen

# --- CODE VERWALTUNG ---
def load_codes():
    if not os.path.exists(CODES_FILE):
        default_data = {"1234": "Admin"}
        with open(CODES_FILE, 'w') as f:
            json.dump(default_data, f)
        return default_data
    
    try:
        with open(CODES_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}

def save_code(code, name):
    data = load_codes()
    data[code] = name
    with open(CODES_FILE, 'w') as f:
        json.dump(data, f)

def delete_code(code):
    data = load_codes()
    if code in data:
        del data[code]
        with open(CODES_FILE, 'w') as f:
            json.dump(data, f)

# --- FLASK WEB-SERVER ---
app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Klingel Manager</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: sans-serif; background-color: #f4f7f6; padding: 20px; }
        .container { max-width: 600px; margin: auto; background: white; padding: 20px; border-radius: 10px; box-shadow: 0 4px 10px rgba(0,0,0,0.1); }
        h1, h2 { color: #333; text-align: center; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        td, th { padding: 10px; border-bottom: 1px solid #eee; text-align: left; }
        input[type=text], input[type=number] { width: 100%; padding: 10px; margin: 5px 0; border: 1px solid #ccc; border-radius: 5px; box-sizing: border-box;}
        button { width: 100%; padding: 10px; border: none; border-radius: 5px; cursor: pointer; color: white; font-weight: bold; margin-top: 5px; }
        .btn-open { background: #27ae60; }
        .btn-add { background: #3498db; }
        .btn-del { background: #e74c3c; width: auto; padding: 5px 10px; font-size: 12px; }
        .btn-down { background: #95a5a6; margin-bottom: 20px; }
        .refresh-link { display:block; text-align:center; margin-bottom:10px; color:#3498db; text-decoration:none; font-weight:bold; font-size:18px;}
    </style>
</head>
<body>
    <div class="container">
        <h1>Tuer & Codes</h1>
        
        <form action="/open" method="post">
            <button type="submit" class="btn-open">JETZT OEFFNEN</button>
        </form>
        <br>
        
        <div style="background:#eee; padding:15px; border-radius:8px;">
            <h2>Neuen Code anlegen</h2>
            <form action="/add_code" method="post">
                <label>Name (Person):</label>
                <input type="text" name="name" placeholder="Name" required>
                <label>Code (4-8 Ziffern):</label>
                <input type="number" name="code" placeholder="1234" required>
                <button type="submit" class="btn-add">Code Speichern</button>
            </form>
        </div>

        <h2>Aktive Codes</h2>
        <table>
            <tr><th>Name</th><th>Code</th><th>Aktion</th></tr>
            {% for code, name in codes.items() %}
            <tr>
                <td>{{ name }}</td>
                <td style="font-family: monospace; font-weight: bold; color: #2c3e50;">{{ code }}</td>
                <td>
                    <form action="/del_code" method="post" style="margin:0;">
                        <input type="hidden" name="code" value="{{ code }}">
                        <button type="submit" class="btn-del">Loeschen</button>
                    </form>
                </td>
            </tr>
            {% endfor %}
        </table>

        <h2>Protokoll</h2>
        <a href="/" class="refresh-link">Liste Aktualisieren</a>
        
        <form action="/download" method="get">
            <button type="submit" class="btn-down">Protokoll herunterladen (.txt)</button>
        </form>

        <table>
            {% for line in logs %}
            <tr><td style="font-size:12px;">{{ line }}</td></tr>
            {% endfor %}
        </table>
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    logs = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            logs = f.readlines()
            logs.reverse()
    return render_template_string(HTML_TEMPLATE, logs=logs[:15], codes=load_codes())

@app.route('/open', methods=['POST'])
def web_open():
    log_and_push("Web-Interface Fernoeffnung")
    trigger_door_async() 
    return redirect(url_for('index'))

@app.route('/add_code', methods=['POST'])
def add_code_route():
    name = request.form.get('name')
    code = request.form.get('code')
    if name and code:
        save_code(code, name)
    return redirect(url_for('index'))

@app.route('/del_code', methods=['POST'])
def del_code_route():
    code = request.form.get('code')
    delete_code(code)
    return redirect(url_for('index'))

@app.route('/download')
def download_log():
    if os.path.exists(LOG_FILE):
        return send_file(LOG_FILE, as_attachment=True)
    return "Kein Log vorhanden"

def run_flask():
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

# --- GUI LOGIK ---

def clear_window():
    for widget in root.winfo_children():
        widget.destroy()
    root.configure(bg=current_theme["bg"])

def apply_theme_auto():
    global current_theme, is_night_mode
    hour = datetime.datetime.now().hour
    should_be_night = (hour >= 18 or hour < 7)
    
    if should_be_night and not is_night_mode:
        current_theme = THEME_NIGHT
        is_night_mode = True
        if len(root.winfo_children()) > 0:
            show_start_screen() 
    elif not should_be_night and is_night_mode:
        current_theme = THEME_DAY
        is_night_mode = False
        if len(root.winfo_children()) > 0:
            show_start_screen() 
    root.after(60000, apply_theme_auto)

def toggle_theme_manual():
    global current_theme, is_night_mode
    if is_night_mode:
        current_theme = THEME_DAY
        is_night_mode = False
    else:
        current_theme = THEME_NIGHT
        is_night_mode = True
    show_start_screen()

def show_start_screen():
    global reset_timer
    if reset_timer:
        root.after_cancel(reset_timer)
        reset_timer = None
    clear_window()
    
    tk.Button(root, text="Modus", font=("Arial", 10),
              bg=current_theme["btn_bg"], fg=current_theme["btn_fg"],
              command=toggle_theme_manual).place(relx=0.95, rely=0.02, anchor="ne")

    tk.Button(root, text="KLINGELN", font=("Arial", 30, "bold"),
              bg=current_theme["bell_bg"], fg="white",
              command=show_selection_screen).place(relx=0.5, rely=0.4, anchor="center", relwidth=0.8, relheight=0.3)

    tk.Label(root, text="Oeffnungszeiten:\n" + OPENING_TEXT, 
             font=("Arial", 14), bg=current_theme["bg"], fg=current_theme["fg"],
             justify="center").place(relx=0.5, rely=0.65, anchor="center")

    tk.Button(root, text="Code Eingabe", font=("Arial", 12),
              bg=current_theme["btn_bg"], fg=current_theme["btn_fg"],
              command=show_pin_pad).place(relx=0.5, rely=0.9, anchor="center", width=200, height=50)

def show_selection_screen():
    global reset_timer
    led_feedback.on()
    play_sound()
    clear_window()
    tk.Label(root, text="Grund waehlen:", font=("Arial", 20, "bold"), 
             bg=current_theme["bg"], fg=current_theme["fg"]).pack(pady=40)
    
    for r in ["Paket / Post", "Besuch", "Lieferdienst", "Sonstiges"]:
        tk.Button(root, text=r, font=("Arial", 16), width=20, height=2,
                  bg=current_theme["btn_bg"], fg=current_theme["btn_fg"],
                  command=lambda res=r: handle_klingel(res)).pack(pady=10)
    
    root.after(2000, led_feedback.off)
    reset_timer = root.after(10000, show_start_screen)

def show_pin_pad():
    global reset_timer
    if reset_timer:
        root.after_cancel(reset_timer)
    clear_window()
    
    tk.Label(root, text="Code eingeben:", font=("Arial", 18), bg=current_theme["bg"], fg=current_theme["fg"]).pack(pady=20)
    pin_entry = tk.Entry(root, font=("Arial", 30), justify='center', show="*")
    pin_entry.pack(pady=10)
    
    def check_pin():
        entered = pin_entry.get()
        codes = load_codes()
        if entered in codes:
            user_name = codes[entered]
            clear_window()
            
            # 1. Sofort Begruessung anzeigen
            tk.Label(root, text="Hallo\n" + user_name, font=("Arial", 25, "bold"), 
                     fg="#2ecc71", bg=current_theme["bg"]).pack(pady=80)
            
            # 2. Parallel dazu Tuer oeffnen (ohne warten)
            log_and_push("Tuer geoeffnet von: " + user_name)
            trigger_door_async()
            
            # 3. Erst nach 3 Sekunden zurueck zum Start
            root.after(3000, show_start_screen)
        else:
            pin_entry.delete(0, tk.END)
            pin_entry.config(bg="#e74c3c")
            root.after(500, lambda: pin_entry.config(bg="white"))

    keypad = tk.Frame(root, bg=current_theme["bg"])
    keypad.pack(pady=10)
    keys = [('1',0,0), ('2',0,1), ('3',0,2), ('4',1,0), ('5',1,1), ('6',1,2),
            ('7',2,0), ('8',2,1), ('9',2,2), ('C',3,0), ('0',3,1), ('OK',3,2)]
    
    for (txt, r, c) in keys:
        if txt == 'OK':
            cmd = check_pin
        elif txt == 'C':
            cmd = lambda: pin_entry.delete(0, tk.END)
        else:
            cmd = lambda t=txt: pin_entry.insert(tk.END, t)

        tk.Button(keypad, text=txt, font=("Arial",18,"bold"), width=5, height=2,
                  bg=current_theme["btn_bg"], fg=current_theme["btn_fg"], command=cmd).grid(row=r, column=c, padx=5, pady=5)
    
    tk.Button(root, text="Abbrechen", font=("Arial",12), command=show_start_screen).pack(pady=20)
    reset_timer = root.after(15000, show_start_screen)

def handle_klingel(reason):
    # Loggen und Pushen passiert immer
    log_and_push(reason)
    clear_window()
    
    # Pruefen ob offen ist
    if check_is_open():
        # JA: Alles normal
        tk.Label(root, text="Vielen Dank!", font=("Arial", 30), fg="#2ecc71", bg=current_theme["bg"]).pack(pady=80)
        tk.Label(root, text="Wir kommen gleich!", font=("Arial", 20), fg=current_theme["fg"], bg=current_theme["bg"]).pack()
    else:
        # NEIN: Geschlossen-Meldung
        tk.Label(root, text="Geschlossen", font=("Arial", 30, "bold"), fg="#e74c3c", bg=current_theme["bg"]).pack(pady=60)
        tk.Label(root, text="Wir sind gerade nicht da.\nNachricht wurde gesendet!", font=("Arial", 16), fg=current_theme["fg"], bg=current_theme["bg"]).pack()

    root.after(6000, show_start_screen)

# --- HINTERGRUND PROZESSE ---

def trigger_door_async():
    """Startet den Tueroeffner in einem eigenen Thread, damit GUI nicht blockiert"""
    threading.Thread(target=_door_thread_func).start()

def _door_thread_func():
    led_door.on()
    sleep(3)
    led_door.off()

def play_sound():
    try:
        buzzer.play("C5"); sleep(0.2); buzzer.play("G4"); sleep(0.4); buzzer.stop()
    except: pass

def log_and_push(text):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a") as f:
        f.write("[{}] {}\n".format(ts, text))
    try:
        requests.post("https://ntfy.sh/"+NTFY_TOPIC, data=text.encode('utf-8'), headers={"Title":"Haustuer","Priority":"high"})
    except: pass

# --- START ---
flask_thread = threading.Thread(target=run_flask)
flask_thread.daemon = True
flask_thread.start()

root = tk.Tk()
root.title("Smarte Klingel")
root.geometry("480x800")

apply_theme_auto()
show_start_screen()
root.mainloop()
