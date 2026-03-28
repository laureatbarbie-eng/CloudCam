from nicegui import ui, app
from pathlib import Path
import csv, time, json, os, psutil

# --- КОНФИГУРАЦИЯ И ПУТИ ---
CONFIG_PATH = Path("/opt/cloudcam/processing/config.json")
try:
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
except FileNotFoundError:
    cfg = {"storage_dir": "/var/lib/cloudcam", "result_csv": "/var/lib/cloudcam/results/vnogo.csv"}

STORAGE_DIR = Path(cfg.get("storage_dir", "/var/lib/cloudcam"))
CSV_PATH = Path(cfg.get("result_csv", "/var/lib/cloudcam/results/vnogo.csv"))
app.add_static_files('/storage', STORAGE_DIR)

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def read_last_vnogo():
    if not CSV_PATH.exists(): return None
    try:
        with CSV_PATH.open("r", encoding="utf-8") as f:
            rows = list(csv.reader(f))
            if len(rows) <= 1: return None
            last = rows[-1]
            return {"cycle_id": int(last[0]), "ts": last[1], "vnogo_m": float(last[2])}
    except Exception: return None

def get_latest_image(cam_id):
    cam_dir = STORAGE_DIR / cam_id
    if not cam_dir.exists(): return None
    images = list(cam_dir.glob("*.jpg"))
    if not images: return None
    latest = max(images, key=os.path.getctime)
    return f"/storage/{cam_id}/{latest.name}?t={time.time()}"

def get_system_stats():
    try: temp = psutil.sensors_temperatures()['cpu_thermal'][0].current
    except: temp = 0.0
    return psutil.cpu_percent(), psutil.virtual_memory().percent, psutil.disk_usage(str(STORAGE_DIR)).percent, temp

# --- ИНТЕРФЕЙС ПРИЛОЖЕНИЯ ---
@ui.page('/')
def main_page():
    # Включаем принудительный темный режим и задаем глубокий черный фон (как у OLED экранов)
    ui.dark_mode().enable()
    ui.add_head_html('<style>body { background-color: #050505; font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; }</style>')
    
    # Шапка: Эффект матового стекла (Glassmorphism), тонкие рамки
    with ui.header().classes('bg-black/70 backdrop-blur-md border-b border-gray-800 px-8 py-4 items-center justify-between'):
        ui.label('СКАЙР').classes('text-2xl font-extrabold tracking-widest text-white')
        ui.button('Перезагрузить', icon='refresh').classes('bg-transparent border border-gray-600 text-gray-300 hover:text-white rounded-full px-6')

    # Контейнер для центрирования контента в стиле современных лендингов
    with ui.column().classes('w-full max-w-7xl mx-auto px-4 py-8'):
        
        # Минималистичные вкладки (Pill-дизайн)
        with ui.tabs().classes('w-full justify-center gap-8 text-gray-400') as tabs:
            tab_dash = ui.tab('Дашборд')
            tab_hw = ui.tab('Оборудование')
            tab_ota = ui.tab('OTA Обновление')
            tab_set = ui.tab('Настройки')

        with ui.tab_panels(tabs, value=tab_dash).classes('w-full bg-transparent mt-8'):
            
            # ==========================================
            # ВКЛАДКА 1: ДАШБОРД (ГЛАВНЫЙ ЭКРАН)
            # ==========================================
            with ui.tab_panel(tab_dash):
                # Hero-секция (Крупная типографика, градиенты)
                with ui.column().classes('w-full items-center py-12'):
                    ui.label('Текущая высота облачности').classes('text-xl text-gray-400 tracking-wide uppercase font-semibold')
                    # Огромный текст с градиентом от синего к фиолетовому
                    vnogo_label = ui.label('-- M').classes('text-[8rem] font-light leading-none text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-purple-500 pb-2')
                    status_label = ui.label('Ожидание синхронизации...').classes('text-lg text-gray-500 mt-4 bg-gray-900 px-6 py-2 rounded-full border border-gray-800')

                # Блок с фотографиями (Большие скругления, плавные тени)
                with ui.row().classes('w-full gap-8 mt-8'):
                    with ui.column().classes('w-full md:w-[calc(50%-1rem)]'):
                        ui.label('120° ULTRA WIDE').classes('text-sm text-gray-500 tracking-widest mb-2 ml-2')
                        img_left = ui.image().classes('w-full aspect-video bg-gray-900 rounded-3xl border border-gray-800 shadow-2xl overflow-hidden').props('fit=cover')
                    
                    with ui.column().classes('w-full md:w-[calc(50%-1rem)]'):
                        ui.label('160° FISHEYE').classes('text-sm text-gray-500 tracking-widest mb-2 ml-2')
                        img_right = ui.image().classes('w-full aspect-video bg-gray-900 rounded-3xl border border-gray-800 shadow-2xl overflow-hidden').props('fit=cover')

                # Таймер обновления дашборда
                def update_dashboard():
                    data = read_last_vnogo()
                    if data:
                        vnogo_label.set_text(f"{data['vnogo_m']:.0f} M")
                        status_label.set_text(f"Цикл: {data['cycle_id']} • {data['ts']}")
                    
                    url_left = get_latest_image('cam120')
                    url_right = get_latest_image('cam160')
                    if url_left: img_left.set_source(url_left)
                    if url_right: img_right.set_source(url_right)

                ui.timer(5.0, update_dashboard)

            # ==========================================
            # ВКЛАДКА 2: ОБОРУДОВАНИЕ (ТЕЛЕМЕТРИЯ)
            # ==========================================
            with ui.tab_panel(tab_hw):
                with ui.row().classes('w-full gap-6'):
                    # Премиальная карточка сервера
                    with ui.card().classes('w-full md:w-1/3 bg-gray-900/50 backdrop-blur rounded-3xl border border-gray-800 p-8 shadow-xl'):
                        ui.icon('dns', size='2rem').classes('text-blue-500 mb-4')
                        ui.label('Сервер (Raspberry Pi)').classes('text-2xl font-semibold text-white mb-6')
                        
                        ui.label('CPU').classes('text-gray-400 text-sm tracking-wide')
                        cpu_bar = ui.linear_progress(value=0.0, color='blue-500').classes('mb-4 h-2 rounded-full')
                        
                        ui.label('RAM').classes('text-gray-400 text-sm tracking-wide')
                        ram_bar = ui.linear_progress(value=0.0, color='purple-500').classes('mb-4 h-2 rounded-full')
                        
                        ui.label('Storage').classes('text-gray-400 text-sm tracking-wide')
                        disk_bar = ui.linear_progress(value=0.0, color='cyan-500').classes('h-2 rounded-full')
                        
                        temp_lbl = ui.label('-- °C').classes('text-3xl font-light text-white mt-8')

                def update_telemetry():
                    cpu, ram, disk, temp = get_system_stats()
                    cpu_bar.set_value(cpu / 100)
                    ram_bar.set_value(ram / 100)
                    disk_bar.set_value(disk / 100)
                    temp_lbl.set_text(f'{temp:.1f} °C')
                
                ui.timer(2.0, update_telemetry)

            # ==========================================
            # ВКЛАДКА 3: OTA ПРОШИВКА
            # ==========================================
            with ui.tab_panel(tab_ota):
                with ui.column().classes('w-full max-w-2xl mx-auto items-center py-12'):
                    ui.icon('cloud_upload', size='4rem').classes('text-gray-600 mb-6')
                    ui.label('Беспроводное обновление').classes('text-3xl font-semibold text-white mb-2')
                    ui.label('Загрузите скомпилированный .bin файл для обновления ESP32-CAM').classes('text-gray-500 text-center mb-10')
                    
                    ui.select(['cam120 (Левая)', 'cam160 (Правая)'], label='Целевое устройство').classes('w-full mb-6').props('dark rounded outlined')
                    ui.upload(label='Перетащите firmware.bin сюда', auto_upload=True).classes('w-full').props('dark')

            # ==========================================
            # ВКЛАДКА 4: НАСТРОЙКИ
            # ==========================================
            with ui.tab_panel(tab_set):
                with ui.card().classes('w-full max-w-2xl mx-auto bg-gray-900/50 backdrop-blur rounded-3xl border border-gray-800 p-8'):
                    ui.label('Глобальные параметры').classes('text-2xl font-semibold text-white mb-8')
                    ui.input('Директория хранения', value=str(STORAGE_DIR)).classes('w-full mb-6').props('dark outlined')
                    ui.button('Экспорт vnogo.csv', icon='download', on_click=lambda: ui.download(CSV_PATH)).classes('w-full py-4 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-semibold tracking-wide')

ui.run(title='Galaxy СКАЙР', port=8080, dark=True, reload=False)
