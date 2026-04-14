#!/usr/bin/env bash
# =============================================================================
#  CloudCam Uninstall Script (v5.0) — Полная очистка системы
# =============================================================================

set -u

# ─── Цвета ─────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${YELLOW}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[ OK ]${NC}  $*"; }
error()   { echo -e "${RED}[ERR ]${NC}  $*"; }

[[ $EUID -ne 0 ]] && { echo "Запускайте через sudo."; exit 1; }

# Переменные (соответствуют install.sh)
INSTALL_DIR="/opt/cloudcam"
DATA_DIR="/var/lib/cloudcam"
AP_CON_NAME="Raspberry"

echo -e "${RED}⚠️  ВНИМАНИЕ: Все данные CloudCam и настройки сети будут удалены!${NC}"
read -rp "Продолжить удаление? [y/N]: " CONFIRM
[[ "${CONFIRM,,}" =~ ^(y|yes|да)$ ]] || { info "Отменено."; exit 0; }

# ─────────────────────────────────────────────────────────────────────────────
info "1. Остановка и удаление Systemd-сервисов..."
# ─────────────────────────────────────────────────────────────────────────────
SERVICES=(
    "cloudcam-server.service" 
    "cloudcam-gui.service" 
    "cloudcam-compute.timer" 
    "cloudcam-compute.service"
)

for svc in "${SERVICES[@]}"; do
    systemctl stop "$svc" 2>/dev/null || true
    systemctl disable "$svc" 2>/dev/null || true
    rm -f "/etc/systemd/system/$svc"
done

systemctl daemon-reload
success "Сервисы удалены."

# ─────────────────────────────────────────────────────────────────────────────
info "2. Очистка сетевых настроек (NetworkManager)..."
# ─────────────────────────────────────────────────────────────────────────────
# Удаляем профиль AP, созданный nmcli
nmcli con delete "$AP_CON_NAME" 2>/dev/null && success "Профиль Wi-Fi '$AP_CON_NAME' удален."

# Удаляем файл блокировки (если остался от старых версий)
rm -f /etc/NetworkManager/conf.d/99-cloudcam-ap.conf

# ─────────────────────────────────────────────────────────────────────────────
info "3. Очистка Nginx и Avahi..."
# ─────────────────────────────────────────────────────────────────────────────
rm -f /etc/nginx/sites-enabled/cloudcam
rm -f /etc/nginx/sites-available/cloudcam
rm -f /etc/avahi/services/cloudcam.service
systemctl reload nginx 2>/dev/null || true
success "Конфигурации веб-сервера удалены."

# ─────────────────────────────────────────────────────────────────────────────
info "4. Удаление утилит из /usr/local/bin..."
# ─────────────────────────────────────────────────────────────────────────────
rm -f /usr/local/bin/cloudcam-calibrate
rm -f /usr/local/bin/cloudcam-status
rm -f /usr/local/bin/cloudcam-logs
success "Бинарные файлы удалены."

# ─────────────────────────────────────────────────────────────────────────────
info "5. Удаление основных директорий..."
# ─────────────────────────────────────────────────────────────────────────────
# Спрашиваем отдельно про данные (снимки/результаты)
read -rp "Удалить папку с данными ($DATA_DIR)? [y/N]: " DEL_DATA
if [[ "${DEL_DATA,,}" =~ ^(y|yes|да)$ ]]; then
    rm -rf "$DATA_DIR"
    success "Данные удалены."
else
    info "Папка $DATA_DIR сохранена."
fi

rm -rf "$INSTALL_DIR"
success "Программные файлы ($INSTALL_DIR) удалены."

# ─────────────────────────────────────────────────────────────────────────────
echo -e "\n${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  Удаление CloudCam завершено успешно!${NC}"
echo -e "  Системные пакеты (OpenCV, Python и др.) не тронуты."
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"