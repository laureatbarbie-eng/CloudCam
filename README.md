# 📸 ESP32-CAM Автоматическая Фотосъемка с Загрузкой на Сервер 🌐

![ESP32](https://img.shields.io/badge/ESP32-FF6600?style=for-the-badge&logo=espressif&logoColor=white)
![Arduino](https://img.shields.io/badge/Arduino-00979D?style=for-the-badge&logo=arduino&logoColor=white)
![PlatformIO](https://img.shields.io/badge/PlatformIO-1A1A1A?style=for-the-badge&logo=platformio&logoColor=00A8FF)
![License](https://img.shields.io/github/license/f2re/esp32cam?style=for-the-badge)
![Issues](https://img.shields.io/github/issues/f2re/esp32cam?style=for-the-badge)
![Forks](https://img.shields.io/github/forks/f2re/esp32cam?style=for-the-badge)
![Stars](https://img.shields.io/github/stars/f2re/esp32cam?style=for-the-badge)

## 📖 Описание проекта

**ESP32-CAM Автоматическая Фотосъемка** — это проект, который позволяет автоматически захватывать фотографии с помощью камеры ESP32-CAM и загружать их на удаленный сервер. Устройство работает автономно, делая снимки по расписанию каждые 10 минут, затем переходит в режим глубокого сна для экономии энергии. После пробуждения устройство подключается к Wi-Fi, делает снимок и отправляет его на сервер.

### 🎯 Основные возможности

- 📷 Автоматическое фотографирование с ESP32-CAM (OV2640)
- 📤 Загрузка фотографий на HTTP-сервер методом POST
- ⏰ Автоматическая съемка по расписанию (по умолчанию каждые 10 минут)
- 😴 Режим глубокого сна между съемками для экономии энергии
- 🌐 Подключение к Wi-Fi для передачи данных
- 🎨 Настройка параметров камеры (качество, формат, баланс белого)
- 🔄 Автоматическая повторная попытка при неудачной загрузке
- 📶 Индикация состояния с помощью светодиодов

### 🛠️ Технические характеристики

- ✅ Микроконтроллер: ESP32 (на плате ESP32-CAM)
- ✅ Камера: OV2640 (до разрешения QXGA 2048×1536 )
- ✅ Память: PSRAM (необходима для работы камеры)
- ✅ Интерфейс: UART, Wi-Fi
- ✅ Питание: 5V USB или 3.3V внешний источник
- ✅ Потребление: минимальное в режиме сна (~10μA)

</div>