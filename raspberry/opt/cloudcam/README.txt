README.txt — CloudCam VNOGO (2×ESP32-CAM OV2640: 120° + 160°) — zenith

0) Цель
Система каждые 10 минут делает синхронную пару снимков неба (cam120 + cam160),
сохраняет изображения и метаданные на Raspberry Pi и рассчитывает ВНГО (высоту нижней границы облачности)
в метрах с записью в CSV/JSONL и (опционально) выводом в отдельном окне.

1) Состав системы
1.1) Железо
- Raspberry Pi 5 (или 4) с Raspberry Pi OS.
- 2× ESP32-CAM AI-Thinker (OV2640) + линзы:
  - камера A: 120° (cam120)
  - камера B: 160° (cam160)
- Питание: стабильные 5V (желательно DC-DC), общий GND.
- 2× USB-TTL (3.3V) или один — прошивать по очереди.
- Жёсткая рама. Для высокой точности желательно обеспечить базис ~0.8–1.0 м
  между центрами объективов и строгое направление в зенит.

1.2) ПО (узлы)
- ESP32-CAM: прошивки main_cam120.cpp и main_cam160.cpp
- Raspberry Pi:
  - /opt/cloudcam/server/app.py — сервер/координатор (hello/waitcmd/upload/waitack)
  - /opt/cloudcam/processing/* — калибровка и вычисление ВНГО

2) Структура каталогов (RPi)
- /opt/cloudcam/server/
  - app.py
  - config.json
  - requirements.txt
- /opt/cloudcam/processing/
  - config.json
  - cbh_compute.py
  - cbh_gui.py (опционально)
  - calib/
    - capture_calib_pairs.py
    - calibrate_fisheye_single.py
    - calibrate_fisheye_stereo.py
  - calib_out/   (сюда пишутся результаты калибровки)
- /var/lib/cloudcam/
  - cam120/  (jpg + json метаданные)
  - cam160/
  - stereo_calib/ (пары шахматки для стерео-калибровки)
  - cam120_calib/ (кадры шахматки для одиночной калибровки)
  - cam160_calib/
  - results/
    - vnogo.csv
    - vnogo.jsonl

3) Подключение ESP32-CAM к USB-TTL
- 5V ↔ 5V
- GND ↔ GND
- U0T(ESP) ↔ RX(USB-TTL)
- U0R(ESP) ↔ TX(USB-TTL)
Прошивка:
- IO0 -> GND, затем RESET.
После прошивки:
- IO0 убрать (не на GND), RESET.

4) Прошивка ESP32-CAM (PlatformIO)
4.1) platformio.ini
- включить PSRAM (BOARD_HAS_PSRAM).
4.2) main_cam120.cpp / main_cam160.cpp
- CAM_ID должен быть cam120 и cam160 соответственно.
- CAPTURE_PERIOD_SEC = 600 (строго 10 минут).
- Реализовано CAPTURE_AT по server_ms и local_ms (выравнивание моментов).
- Upload отправляет multipart:
  - поле meta (JSON)
  - поле file (jpeg)
Проверка в Serial:
- должны быть логи [TIMING] wifi_connect, hello, waitcmd, capture, upload, waitack, затем sleep.

5) Настройка Raspberry Pi (сервер)
5.1) Установка зависимостей
sudo apt update
sudo apt install -y python3 python3-venv

5.2) Развёртывание сервера
sudo mkdir -p /opt/cloudcam/server
sudo chown -R pi:pi /opt/cloudcam
cd /opt/cloudcam/server
python3 -m venv venv
./venv/bin/pip install -r requirements.txt

5.3) Каталоги данных
sudo mkdir -p /var/lib/cloudcam/cam120 /var/lib/cloudcam/cam160 /var/lib/cloudcam/results
sudo chown -R pi:pi /var/lib/cloudcam

5.4) systemd
sudo cp /opt/cloudcam/server/cloudcam.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable cloudcam.service
sudo systemctl restart cloudcam.service
Проверка:
curl http://192.168.4.1:8000/health

6) Контроль получения кадров
- Подключите обе камеры к Wi-Fi AP.
- Дождитесь 1–2 циклов.
- В /var/lib/cloudcam/cam120 и /var/lib/cloudcam/cam160 должны появляться:
  - <cycle>_<UTCts>.jpg
  - <cycle>_<UTCts>.json
В json смотрите:
- rssi, capture_ms, jpeg_bytes, time_valid, cmd_server_ms, t_capture_ms.

7) Калибровка (обязательная часть для точности)
Важно: у вас линзы 120/160°, это fisheye, нужна fisheye-модель OpenCV.

7.1) Подготовка шахматки
- Распечатайте шахматку 9x6 внутренних углов.
- Точно измерьте размер клетки (например 30 мм).
- Для калибровки делайте кадры так, чтобы шахматка попадала и в центр, и в края кадра.

7.2) Съёмка калибровочных кадров
- Запускаете систему в обычном режиме (каждые 10 минут).
- Перед камерами держите шахматку под разными углами/положениями.
- Соберите 20–40 циклов с шахматкой.

7.3) Выделение последних N пар для калибровки
python3 /opt/cloudcam/processing/calib/capture_calib_pairs.py --n 30
После этого появятся:
- /var/lib/cloudcam/stereo_calib/<cycle>_cam120.jpg и <cycle>_cam160.jpg
- /var/lib/cloudcam/cam120_calib/<cycle>.jpg
- /var/lib/cloudcam/cam160_calib/<cycle>.jpg

7.4) Одиночная калибровка (intrinsics)
python3 /opt/cloudcam/processing/calib/calibrate_fisheye_single.py  (CAM_ID=cam120)
python3 /opt/cloudcam/processing/calib/calibrate_fisheye_single.py  (CAM_ID=cam160)
Результаты:
- /opt/cloudcam/processing/calib_out/cam120_fisheye.yml
- /opt/cloudcam/processing/calib_out/cam160_fisheye.yml

7.5) Стерео калибровка (extrinsics + rectification)
python3 /opt/cloudcam/processing/calib/calibrate_fisheye_stereo.py
Результат:
- /opt/cloudcam/processing/calib_out/stereo_fisheye.yml

8) Расчёт ВНГО
8.1) Конфиг
Отредактируйте /opt/cloudcam/processing/config.json:
- storage_dir = /var/lib/cloudcam
- cam_left = cam120
- cam_right = cam160
- calib_dir = /opt/cloudcam/processing/calib_out
- min_height_m / max_height_m

8.2) Запуск расчёта вручную
python3 /opt/cloudcam/processing/cbh_compute.py
Выход:
- /var/lib/cloudcam/results/vnogo.csv
- /var/lib/cloudcam/results/vnogo.jsonl

8.3) Окно вывода (опционально)
python3 /opt/cloudcam/processing/cbh_gui.py

9) Как интерпретируется высота (зенит)
- Камеры смотрят строго в зенит.
- После rectification и триангуляции высота ВНГО оценивается по глубине вдоль оптической оси (Z),
поскольку оптическая ось направлена вверх.
- Итог ВНГО берётся как нижний перцентиль по высоте среди валидных 3D-точек в центральном ROI.

10) Надёжность и типовые проблемы
10.1) WDT/зависания на ESP32
- Используйте неблокирующее чтение HTTP с таймаутами (readLine + общий timeout).
- Смотрите тайминги [TIMING] для выявления “где пропали секунды”.

10.2) Capture FAILED / нестабильный захват
- Уменьшить frame_size (VGA -> QVGA).
- Снизить xclk_freq_hz 20MHz -> 10MHz.
- fb_count=1 и grab_mode=WHEN_EMPTY (если нужно).

10.3) Плохой Wi‑Fi (долгий upload)
- Смотрите rssi в meta.json.
- Увеличьте окно UPLOAD_WAIT_SEC на сервере (waitack), если нужно.
- Убедитесь, что WiFi.setSleep(false) включён (иначе power-save может ломать long-poll).

11) Режим “ночь”
- На OV2640 ночью текстура облаков часто недостаточна без подсветки/светового фона.
- Для ночи в перспективе потребуется отдельное исследование: выдержки, шум/компрессия, критерии достоверности.

12) Что считается “успешной установкой”
- Каждые 10 минут появляются пары jpg/json для обеих камер.
- Раз в 10 минут или по запуску cbh_compute.py добавляется строка в vnogo.csv.
- GUI показывает последнее значение VNOGO.

Конец README
