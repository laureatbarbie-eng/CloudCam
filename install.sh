#!/usr/bin/env bash
# =============================================================================
#  CloudCam — скрипт развертывания для Raspberry Pi 5  (v4.0)
#  Репозиторий: https://github.com/laureatbarbie-eng/CloudCam
#
#  Запуск: sudo bash deploy_cloudcam.sh [параметры]
#
#  Параметры:
#    --ssid   ИМЯ     SSID точки доступа    (по умолчанию: Raspberry)
#    --pass   ПАРОЛЬ  Пароль AP             (по умолчанию: 12345678)
#    --ip     IP      IP-адрес AP           (по умолчанию: 192.168.4.1)
#    --user   ИМЯ     Пользователь          (по умолчанию: $SUDO_USER)
#    --wifi   IFACE   AP-интерфейс          (по умолчанию: wlan1)
#    --skip-ap        Пропустить настройку AP
#    --help           Справка
# =============================================================================
# Список изменений v4.0:
#   - venv всегда пересоздаётся с --system-site-packages (фикс проблем 4, 3)
#   - OpenCV берётся ТОЛЬКО из APT, pip-ветка полностью удалена (фикс 2, 7)
#   - Проверка сети: только deb.debian.org + github.com (pip офлайн, PyPI не нужен)
#   - safe_pip не использует wait_for_dns — пинг делается внутри каждого вызова (фикс 5)
#   - Нет единого большого pip install — каждый пакет отдельно (фикс 8)
#   - Идемпотентность: повторный запуск не ломает уже рабочее окружение (фикс 8)
# =============================================================================

set -euo pipefail

# ─── Цвета ─────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[ OK ]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERR ]${NC}  $*" >&2; exit 1; }
step()    {
  echo -e "\n${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${BOLD}  $*${NC}"
  echo -e "${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

# ─── Параметры по умолчанию ────────────────────────────────────────────────
SCRIPT_VERSION="5.0"
AP_SSID="Raspberry"
AP_PASS="12345678"
AP_IP="192.168.4.1"
AP_CHANNEL="6"
AP_IFACE="wlan1"      # USB MT7612U; wlan0 — встроенный, остаётся клиентом
SKIP_AP=false
REPO_URL="https://github.com/laureatbarbie-eng/CloudCam.git"
INSTALL_DIR="/opt/cloudcam"
DATA_DIR="/var/lib/cloudcam"
CLOUDCAM_USER="${SUDO_USER:-pi}"

# ─── Аргументы CLI ─────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --ssid)    AP_SSID="$2";       shift 2 ;;
    --pass)    AP_PASS="$2";       shift 2 ;;
    --ip)      AP_IP="$2";         shift 2 ;;
    --user)    CLOUDCAM_USER="$2"; shift 2 ;;
    --wifi)    AP_IFACE="$2";      shift 2 ;;
    --skip-ap) SKIP_AP=true;       shift   ;;
    --help|-h) sed -n '5,14p' "$0"; exit 0 ;;
    *) warn "Неизвестный аргумент: $1"; shift ;;
  esac
done

# ─── Предварительные проверки ──────────────────────────────────────────────
[[ $EUID -ne 0 ]]        && error "Запускайте через sudo."
[[ -z "$CLOUDCAM_USER" ]] && CLOUDCAM_USER="pi"

VENV_DIR="${INSTALL_DIR}/venv"

info "deploy_cloudcam.sh v${SCRIPT_VERSION}"

# Версия ОС
if [[ -f /etc/os-release ]]; then
  # shellcheck source=/dev/null
  source /etc/os-release
  info "ОС: ${PRETTY_NAME:-unknown}"
  if [[ "${VERSION_CODENAME:-}" == "bullseye" || "${VERSION_CODENAME:-}" == "buster" ]]; then
    warn "Старая ОС (${VERSION_CODENAME}). Рекомендуется Bookworm."
  fi
fi

# Проверка интернета: только APT и GitHub нужны онлайн.
# pip работает ОФЛАЙН из локальных wheel-файлов — PyPI не проверяем.
info "Проверка интернет-соединения (APT + GitHub)..."
INET_OK=true
for host in deb.debian.org github.com; do
  if curl -sf --max-time 10 "https://${host}" -o /dev/null 2>&1; then
    info "  ✓ ${host}"
  else
    warn "  ✗ ${host} недоступен"
    INET_OK=false
  fi
done
[[ "$INET_OK" == "false" ]] && \
  error "Нет доступа к APT или GitHub. Проверьте сеть и повторите."

# ─── Баннер ────────────────────────────────────────────────────────────────
echo -e "\n${BOLD}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║    CloudCam — Развертывание на Raspberry Pi 5  v5.0 ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${NC}\n"
echo -e "  Пользователь : ${BOLD}${CLOUDCAM_USER}${NC}"
echo -e "  AP интерфейс : ${BOLD}${AP_IFACE}${NC}  (USB MT7612U)"
echo -e "  AP SSID      : ${BOLD}${AP_SSID}${NC}"
echo -e "  AP IP        : ${BOLD}${AP_IP}${NC}"
echo -e "  Установка в  : ${BOLD}${INSTALL_DIR}${NC}"
echo -e "  Данные       : ${BOLD}${DATA_DIR}${NC}"
[[ "$SKIP_AP" == "true" ]] && echo -e "  ${YELLOW}⚠  Настройка AP пропущена (--skip-ap)${NC}"
echo

read -rp "$(echo -e "${YELLOW}Начать установку? [y/N]:${NC} ")" CONFIRM
[[ "${CONFIRM,,}" =~ ^(y|yes|да)$ ]] || { info "Отменено."; exit 0; }

# Всё дальнейшее пишется в лог
LOG_FILE="/var/log/cloudcam_deploy_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1
info "Лог: ${LOG_FILE}"

# =============================================================================
# ФАЗА 1 — ВСЁ ЧТО ТРЕБУЕТ ИНТЕРНЕТА
# wlan0 сейчас подключён к телефону / роутеру — не трогаем его
# =============================================================================

# ─────────────────────────────────────────────────────────────────────────────
step "ФАЗА 1 · ШАГ 1/4 — APT: системные пакеты"
# ─────────────────────────────────────────────────────────────────────────────

# safe_apt: сначала группой, при ошибке — по одному (не роняет скрипт)
safe_apt() {
  local desc="$1"; shift
  info "APT: ${desc}..."
  if apt-get install -y -qq --no-install-recommends "$@" 2>/dev/null; then
    success "APT OK: ${desc}"
    return 0
  fi
  warn "Групповая установка не удалась — пробуем по одному..."
  local pkg
  for pkg in "$@"; do
    if apt-get install -y -qq --no-install-recommends "$pkg" 2>/dev/null; then
      info "  ✓ ${pkg}"
    else
      warn "  ✗ ${pkg} — пакет недоступен, пропускаем"
    fi
  done
}

apt-get update -qq
apt-get upgrade -y -qq

safe_apt "базовые утилиты"    git curl wget ca-certificates rsync
safe_apt "Python 3"           python3 python3-pip python3-venv python3-dev

# OpenCV через APT — единственный источник на ARM.
# libatlas-base-dev отсутствует в Bookworm → libopenblas-dev
safe_apt "OpenCV (APT)"       python3-opencv libopencv-dev libopenblas-dev \
                              libjpeg-dev libpng-dev libtiff-dev gfortran

safe_apt "сеть / AP"          hostapd dnsmasq \
                              iptables iptables-persistent \
                              rfkill iw wireless-tools
safe_apt "веб / сервисы"      nginx avahi-daemon
safe_apt "сборка"             jq build-essential cmake pkg-config

success "Системные пакеты установлены"

# Драйвер MT7612U
info "Проверка драйвера MT7612U..."
modprobe mt76x2u 2>/dev/null || modprobe mt76x2 2>/dev/null || \
  warn "mt76x2u не загружен — возможно встроен в ядро"
grep -q "mt76x2u" /etc/modules 2>/dev/null || echo "mt76x2u" >> /etc/modules
success "Драйвер MT7612U проверен"

# ─────────────────────────────────────────────────────────────────────────────
step "ФАЗА 1 · ШАГ 2/4 — Git: загрузка только Raspberry-части репозитория"
# ─────────────────────────────────────────────────────────────────────────────

TMP_REPO="/tmp/cloudcam_repo_sparse"
RPI_SUBDIR="raspberry"
RPI_OPT_SUBDIR="${RPI_SUBDIR}/opt/cloudcam"
RPI_VAR_SUBDIR="${RPI_SUBDIR}/var/lib/cloudcam"

info "Подготавливаем временную директорию..."
rm -rf "$TMP_REPO"
mkdir -p "$TMP_REPO"

info "Скачиваем из GitHub только Raspberry-часть репозитория..."
git clone --depth=1 --filter=blob:none --sparse "$REPO_URL" "$TMP_REPO"
git -C "$TMP_REPO" sparse-checkout set "$RPI_OPT_SUBDIR" "$RPI_VAR_SUBDIR"

[[ -d "${TMP_REPO}/${RPI_OPT_SUBDIR}" ]] || error "Не найдена директория ${RPI_OPT_SUBDIR} в репозитории"
[[ -d "${TMP_REPO}/${RPI_VAR_SUBDIR}" ]] || error "Не найдена директория ${RPI_VAR_SUBDIR} в репозитории"

info "Создаём целевые директории..."
mkdir -p "$INSTALL_DIR" "$DATA_DIR"

info "Копируем содержимое ${RPI_OPT_SUBDIR} -> ${INSTALL_DIR} ..."
cp -a "${TMP_REPO}/${RPI_OPT_SUBDIR}/." "$INSTALL_DIR/"

info "Копируем содержимое ${RPI_VAR_SUBDIR} -> ${DATA_DIR} ..."
cp -a "${TMP_REPO}/${RPI_VAR_SUBDIR}/." "$DATA_DIR/"

info "Гарантируем обязательные каталоги данных..."
mkdir -p \
  "${DATA_DIR}/cam120" \
  "${DATA_DIR}/cam160" \
  "${DATA_DIR}/results" \
  "${DATA_DIR}/stereo_calib" \
  "${DATA_DIR}/cam120_calib" \
  "${DATA_DIR}/cam160_calib" \
  "${INSTALL_DIR}/processing/calib_out" \
  "${INSTALL_DIR}/logs" \
  "${INSTALL_DIR}/vendor/wheels"

[[ -f "${INSTALL_DIR}/processing/cbh_gui.py" ]] || warn "Не найден ${INSTALL_DIR}/processing/cbh_gui.py"
[[ -f "${INSTALL_DIR}/server/app.py" ]] || warn "Не найден ${INSTALL_DIR}/server/app.py"
[[ -f "${INSTALL_DIR}/server/requirements.txt" ]] || warn "Не найден ${INSTALL_DIR}/server/requirements.txt"

chown -R "${CLOUDCAM_USER}:${CLOUDCAM_USER}" "$INSTALL_DIR" "$DATA_DIR"
chmod -R 755 "$INSTALL_DIR"
chmod -R 775 "$DATA_DIR"

info "Удаляем временную копию репозитория..."
rm -rf "$TMP_REPO"

success "Raspberry-часть репозитория разложена в ${INSTALL_DIR} и ${DATA_DIR}"

# ─────────────────────────────────────────────────────────────────────────────
step "ФАЗА 1 · ШАГ 3/4 — Python venv + wheelhouse + offline pip"
# ─────────────────────────────────────────────────────────────────────────────

WHEEL_DIR="${INSTALL_DIR}/vendor/wheels"
REQ_OFFLINE="${INSTALL_DIR}/vendor/requirements-offline.txt"

# Пересоздаём venv
if [[ -d "$VENV_DIR" ]]; then
  info "Удаляем старый venv..."
  rm -rf "$VENV_DIR"
fi

info "Создание venv с --system-site-packages..."
sudo -u "${CLOUDCAM_USER}" python3 -m venv --system-site-packages "$VENV_DIR"

PIP="${VENV_DIR}/bin/pip"
PYTHON="${VENV_DIR}/bin/python"

# Проверка OpenCV из APT
if "$PYTHON" -c "import cv2" 2>/dev/null; then
  CV2_VER=$("$PYTHON" -c "import cv2; print(cv2.__version__)" 2>/dev/null || echo "?")
  success "cv2 доступен в venv через APT (версия ${CV2_VER})"
else
  error "cv2 не найден в venv. Проверьте python3-opencv: dpkg -l python3-opencv"
fi

# Строго оффлайн: wheelhouse и список пакетов должны приехать вместе с репозиторием.
# В этой среде pip download может быть недоступен (например, требуется VPN), поэтому
# не пытаемся скачивать зависимости автоматически.
[[ -f "$REQ_OFFLINE" ]] || error "Не найден файл оффлайн-зависимостей: $REQ_OFFLINE"
[[ -d "$WHEEL_DIR" ]] || error "Не найдена директория wheelhouse: $WHEEL_DIR"
find "$WHEEL_DIR" -maxdepth 1 -name '*.whl' | grep -q . || \
  error "В $WHEEL_DIR нет .whl. Добавьте wheel-пакеты в репозиторий заранее."

# Обновление pip/setuptools/wheel оффлайн, если такие wheel уже есть
info "Пробуем оффлайн-обновление pip/setuptools/wheel..."
sudo -u "${CLOUDCAM_USER}" "$PIP" install \
  --no-index \
  --find-links="$WHEEL_DIR" \
  --upgrade pip setuptools wheel || \
  warn "Не удалось обновить pip/setuptools/wheel оффлайн — продолжаем"

# Основная оффлайн-установка
info "Установка Python-зависимостей из локальной папки..."
sudo -u "${CLOUDCAM_USER}" "$PIP" install \
  --no-index \
  --find-links="$WHEEL_DIR" \
  -r "$REQ_OFFLINE"

success "Python-пакеты установлены из локальной папки"

# Проверка импортов
info "Проверка импортов в venv..."
FAILED_IMPORTS=()

for mod in cv2 flask gunicorn nicegui numpy scipy yaml requests PIL matplotlib pandas websockets aiohttp watchdog psutil; do
  if "$PYTHON" -c "import ${mod}" 2>/dev/null; then
    info "  ✓ ${mod}"
  else
    warn "  ✗ ${mod}"
    FAILED_IMPORTS+=("$mod")
  fi
done

if [[ ${#FAILED_IMPORTS[@]} -gt 0 ]]; then
  warn "Не импортируются модули: ${FAILED_IMPORTS[*]}"
  warn "Проверьте, все ли wheel-файлы скопированы в ${WHEEL_DIR}"
else
  success "Все модули импортируются корректно"
fi

success "Python-окружение готово: ${VENV_DIR}"

# ─────────────────────────────────────────────────────────────────────────────
step "ФАЗА 1 · ШАГ 4/4 — Автодетект аргументов калибровочных скриптов"
# ─────────────────────────────────────────────────────────────────────────────

# Функция: парсит add_argument() в Python-файле и возвращает реальный флаг.
# Результат сохраняется в .calib_flags и перечитывается при каждом
# вызове cloudcam-calibrate — флаги всегда актуальны после git pull.
detect_argparse_flag() {
  local script="$1"; shift
  local candidates=("$@")   # приоритетный список: первый найденный побеждает
  [[ ! -f "$script" ]] && echo "${candidates[-1]}" && return
  local candidate
  for candidate in "${candidates[@]}"; do
    if grep -qE "add_argument\s*\(\s*['\"]${candidate}['\"]" "$script" 2>/dev/null; then
      echo "$candidate"
      return
    fi
  done
  echo "${candidates[-1]}"   # fallback — последний в списке
}

SINGLE="${INSTALL_DIR}/processing/calib/calibrate_fisheye_single.py"
STEREO="${INSTALL_DIR}/processing/calib/calibrate_fisheye_stereo.py"
PAIRS="${INSTALL_DIR}/processing/calib/capture_calib_pairs.py"

CAM_FLAG=$(detect_argparse_flag "$SINGLE"  "--cam_id" "--camera_id" "--camera" "--cam")
N_FLAG=$(detect_argparse_flag   "$PAIRS"   "--count"  "--num"       "--pairs"  "--n")

info "Флаг камеры (calibrate_fisheye_single.py): ${CAM_FLAG}"
info "Флаг числа пар (capture_calib_pairs.py):   ${N_FLAG}"

mkdir -p "${INSTALL_DIR}/processing"
cat > "${INSTALL_DIR}/processing/.calib_flags" <<FLAGS
# Автоматически определено deploy_cloudcam.sh v${SCRIPT_VERSION}  $(date)
# Перезаписывается при каждом запуске deploy или cloudcam-calibrate
CAM_FLAG="${CAM_FLAG}"
N_FLAG="${N_FLAG}"
SINGLE_SCRIPT="${SINGLE}"
STEREO_SCRIPT="${STEREO}"
PAIRS_SCRIPT="${PAIRS}"
VENV_DIR="${VENV_DIR}"
FLAGS
chown "${CLOUDCAM_USER}:${CLOUDCAM_USER}" "${INSTALL_DIR}/processing/.calib_flags"
success "Флаги калибровки: CAM=${CAM_FLAG}  N=${N_FLAG}"

# =============================================================================
# ФАЗА 2 — СЕТЬ: ИЗОЛЯЦИЯ NM + ТОЧКА ДОСТУПА
# Все пакеты и репо скачаны — теперь безопасно переключаем wlan1
# =============================================================================

if [[ "$SKIP_AP" == "true" ]]; then
  warn "Настройка AP пропущена (--skip-ap)"
else

# ─────────────────────────────────────────────────────────────────────────────
step "ФАЗА 2 · ШАГ 1/1 — NetworkManager: создание профиля AP"
# ─────────────────────────────────────────────────────────────────────────────

info "Удаление конфликтующих демонов (dhcpcd, hostapd, dnsmasq)..."
apt-get purge -y -qq dhcpcd hostapd dnsmasq iptables-persistent 2>/dev/null || true
rm -f /etc/NetworkManager/conf.d/99-cloudcam-ap.conf

info "Сброс состояния NetworkManager..."
systemctl restart NetworkManager
sleep 3

# Удаление существующего профиля, если скрипт запускается повторно
nmcli con delete CloudCamAP 2>/dev/null || true

info "Создание профиля точки доступа (SSID: ${AP_SSID})..."
nmcli con add \
  type wifi \
  ifname "${AP_IFACE}" \
  con-name Raspberry \
  autoconnect yes \
  ssid "${AP_SSID}"

info "Настройка параметров маршрутизации и безопасности (WPA2, NAT)..."
# ipv4.method shared автоматически поднимает DHCP-сервер и NAT
nmcli con modify Raspberry \
  802-11-wireless.mode ap \
  802-11-wireless.band bg \
  ipv4.method shared \
  ipv4.addresses "${AP_IP}/24" \
  wifi-sec.key-mgmt wpa-psk \
  wifi-sec.psk "${AP_PASS}"

info "Активация точки доступа..."
if nmcli con up Raspberry; then
  success "Точка доступа ${AP_SSID} успешно поднята на ${AP_IFACE}"
else
  error "Не удалось поднять AP. Проверьте rfkill (заблокирован ли Wi-Fi) и драйвер mt76x2u."
fi

fi  # конец блока настройки AP

# =============================================================================
# ФАЗА 3 — КОНФИГУРАЦИЯ СЕРВИСОВ
# =============================================================================

# ─────────────────────────────────────────────────────────────────────────────
step "ФАЗА 3 · ШАГ 1/3 — Nginx"
# ─────────────────────────────────────────────────────────────────────────────
cat > /etc/nginx/sites-available/cloudcam <<NGINX
server {
    listen 80 default_server;
    server_name _;
    client_max_body_size 64M;

    # NiceGUI (WebSocket)
    location / {
        proxy_pass         http://127.0.0.1:8080;
        proxy_set_header   Host              \$host;
        proxy_set_header   X-Real-IP         \$remote_addr;
        proxy_set_header   X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade           \$http_upgrade;
        proxy_set_header   Connection        "upgrade";
        proxy_read_timeout 3600;
        proxy_send_timeout 3600;
    }

    # REST API
    location /api/ {
        proxy_pass       http://127.0.0.1:8000/;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }

    location /health {
        proxy_pass http://127.0.0.1:8000/health;
    }

    # Просмотр снимков
    location /data/ {
        alias     ${DATA_DIR}/;
        autoindex on;
        autoindex_exact_size off;
        autoindex_localtime  on;
    }
}
NGINX
ln -sfn /etc/nginx/sites-available/cloudcam /etc/nginx/sites-enabled/cloudcam
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable nginx
success "Nginx настроен"

# ─────────────────────────────────────────────────────────────────────────────
step "ФАЗА 3 · ШАГ 2/3 — Systemd-сервисы CloudCam"
# ─────────────────────────────────────────────────────────────────────────────

CONFIG_FILE="${INSTALL_DIR}/server/config.json"
mkdir -p "${INSTALL_DIR}/server"
if [[ ! -f "$CONFIG_FILE" ]]; then
  cat > "$CONFIG_FILE" <<JSON
{
  "server":    { "host": "0.0.0.0", "port": 8000, "debug": false },
  "cameras": {
    "cam120":  { "id": "cam120", "fov_deg": 120, "timeout_sec": 30 },
    "cam160":  { "id": "cam160", "fov_deg": 160, "timeout_sec": 30 }
  },
  "capture":   { "period_sec": 600, "sync_tolerance_sec": 2 },
  "data_dir":   "${DATA_DIR}",
  "calib_dir":  "${INSTALL_DIR}/processing/calib_out",
  "results_dir":"${DATA_DIR}/results",
  "ap":        { "ssid": "${AP_SSID}", "ip": "${AP_IP}" }
}
JSON
  chown "${CLOUDCAM_USER}:${CLOUDCAM_USER}" "$CONFIG_FILE"
fi

# Общий блок Environment (подставляется в каждый юнит)
ENV_BLOCK="Environment=\"PATH=${VENV_DIR}/bin:/usr/local/bin:/usr/bin:/bin\"
Environment=\"CLOUDCAM_DATA_DIR=${DATA_DIR}\"
Environment=\"CLOUDCAM_INSTALL_DIR=${INSTALL_DIR}\"
Environment=\"CLOUDCAM_CONFIG=${CONFIG_FILE}\""

cat > /etc/systemd/system/cloudcam-server.service <<UNIT
[Unit]
Description=CloudCam Coordinator Server (Gunicorn)
After=network.target

[Service]
Type=simple
User=${CLOUDCAM_USER}
WorkingDirectory=${INSTALL_DIR}/server
${ENV_BLOCK}
ExecStart=${VENV_DIR}/bin/gunicorn \\
    --bind 127.0.0.1:8000 --workers 2 --timeout 120 --keep-alive 5 \\
    --access-logfile ${INSTALL_DIR}/logs/access.log \\
    --error-logfile  ${INSTALL_DIR}/logs/error.log \\
    app:app
Restart=on-failure
RestartSec=5
SyslogIdentifier=cloudcam-server

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/cloudcam-gui.service <<UNIT
[Unit]
Description=CloudCam Web Dashboard (NiceGUI)
After=cloudcam-server.service

[Service]
Type=simple
User=${CLOUDCAM_USER}
WorkingDirectory=${INSTALL_DIR}/processing
${ENV_BLOCK}
Environment="NICEGUI_HOST=127.0.0.1"
Environment="NICEGUI_PORT=8080"
ExecStart=${VENV_DIR}/bin/python cbh_gui.py
Restart=on-failure
RestartSec=5
SyslogIdentifier=cloudcam-gui

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/cloudcam-compute.service <<UNIT
[Unit]
Description=CloudCam CBH Compute (one-shot)
After=cloudcam-server.service

[Service]
Type=oneshot
User=${CLOUDCAM_USER}
WorkingDirectory=${INSTALL_DIR}/processing
${ENV_BLOCK}
ExecStart=${VENV_DIR}/bin/python cbh_compute.py
SyslogIdentifier=cloudcam-compute
UNIT

cat > /etc/systemd/system/cloudcam-compute.timer <<UNIT
[Unit]
Description=CloudCam CBH Compute каждые 2 мин

[Timer]
OnBootSec=2min
OnUnitActiveSec=2min
AccuracySec=30s

[Install]
WantedBy=timers.target
UNIT

systemctl daemon-reload
systemctl enable cloudcam-server cloudcam-gui cloudcam-compute.timer
systemctl start cloudcam-server cloudcam-gui cloudcam-compute.timer || \
  warn "Не удалось сразу запустить cloudcam-* сервисы, они будут подняты после перезагрузки"
success "Systemd-сервисы зарегистрированы"

# ─────────────────────────────────────────────────────────────────────────────
step "ФАЗА 3 · ШАГ 3/3 — Утилиты и mDNS"
# ─────────────────────────────────────────────────────────────────────────────

# ── cloudcam-calibrate ────────────────────────────────────────────────────
cat > /usr/local/bin/cloudcam-calibrate <<'CALIB'
#!/usr/bin/env bash
# cloudcam-calibrate [N]  — калибровка камер (по умолчанию 30 пар)
set -euo pipefail
PROC="/opt/cloudcam/processing"
FLAGS="${PROC}/.calib_flags"
N="${1:-30}"

# Загружаем флаги
# shellcheck source=/dev/null
[[ -f "$FLAGS" ]] && source "$FLAGS" || {
  VENV_DIR="/opt/cloudcam/venv"
  CAM_FLAG="--cam"; N_FLAG="--n"
  SINGLE_SCRIPT="${PROC}/calib/calibrate_fisheye_single.py"
  STEREO_SCRIPT="${PROC}/calib/calibrate_fisheye_stereo.py"
  PAIRS_SCRIPT="${PROC}/calib/capture_calib_pairs.py"
}

# Перепроверяем флаги из кода скриптов (актуально после git pull)
if [[ -f "$SINGLE_SCRIPT" ]]; then
  for f in "--cam_id" "--camera_id" "--camera" "--cam"; do
    if grep -qE "add_argument\s*\(\s*['\"]${f}['\"]" "$SINGLE_SCRIPT" 2>/dev/null; then
      CAM_FLAG="$f"; break
    fi
  done
fi
if [[ -f "$PAIRS_SCRIPT" ]]; then
  for f in "--count" "--num" "--pairs" "--n"; do
    if grep -qE "add_argument\s*\(\s*['\"]${f}['\"]" "$PAIRS_SCRIPT" 2>/dev/null; then
      N_FLAG="$f"; break
    fi
  done
fi

echo "╔══════════════════════════════════════════╗"
echo "║     CloudCam — Калибровка камер          ║"
echo "╚══════════════════════════════════════════╝"
printf "  Флаг камеры : %s\n"  "$CAM_FLAG"
printf "  Флаг числа  : %s\n"  "$N_FLAG"
printf "  Пар снимков : %s\n\n" "$N"

echo "━━ [1/3] Сбор пар..."
"${VENV_DIR}/bin/python" "${PAIRS_SCRIPT}" "${N_FLAG}" "${N}"

echo "━━ [2/3] cam120..."
"${VENV_DIR}/bin/python" "${SINGLE_SCRIPT}" "${CAM_FLAG}" "cam120"

echo "━━ [2/3] cam160..."
"${VENV_DIR}/bin/python" "${SINGLE_SCRIPT}" "${CAM_FLAG}" "cam160"

echo "━━ [3/3] Стерео..."
"${VENV_DIR}/bin/python" "${STEREO_SCRIPT}"

echo; echo "✓ Готово. Файлы:"
ls -lh "${PROC}/calib_out/"*.yml 2>/dev/null || echo "  (yml не найдены)"
CALIB
chmod +x /usr/local/bin/cloudcam-calibrate

# ── cloudcam-status ───────────────────────────────────────────────────────
cat > /usr/local/bin/cloudcam-status <<STATUS
#!/usr/bin/env bash
AP_IP="${AP_IP}"; AP_IFACE="${AP_IFACE}"; AP_SSID="${AP_SSID}"
DATA_DIR="${DATA_DIR}"
echo -e "\n\033[1m╔══════════════════════════════════════════╗\033[0m"
echo -e "\033[1m║      CloudCam — статус системы           ║\033[0m"
echo -e "\033[1m╚══════════════════════════════════════════╝\033[0m"
echo -e "\n\033[1m  Сервисы:\033[0m"
for s in cloudcam-server cloudcam-gui hostapd dnsmasq nginx avahi-daemon; do
  st=\$(systemctl is-active "\$s" 2>/dev/null || echo inactive)
  [[ "\$st" == active ]] \
    && echo -e "    \033[32m●\033[0m \$s" \
    || echo -e "    \033[31m●\033[0m \$s (\$st)"
done
echo -e "\n\033[1m  Таймер ВНГО:\033[0m"
systemctl status cloudcam-compute.timer --no-pager 2>/dev/null \
  | grep -E "Active|Trigger" | sed 's/^/    /'
echo -e "\n\033[1m  AP (\${AP_IFACE}):\033[0m"
ip addr show "\${AP_IFACE}" 2>/dev/null | awk '/inet /{print "    IP: "\$2}' \
  || echo "    (интерфейс не найден)"
echo "    SSID: \${AP_SSID}"
echo -e "\n\033[1m  DHCP-клиенты:\033[0m"
awk '{print "    "\$4"  ("\$3")"}' /var/lib/misc/dnsmasq.leases 2>/dev/null \
  || echo "    (нет данных)"
echo -e "\n\033[1m  Последний ВНГО:\033[0m"
tail -3 "\${DATA_DIR}/results/vnogo.csv" 2>/dev/null | sed 's/^/    /' \
  || echo "    (нет данных)"
echo -e "\n  http://\${AP_IP}/   |   http://cloudcam.local/\n"
STATUS
chmod +x /usr/local/bin/cloudcam-status

# ── cloudcam-logs ─────────────────────────────────────────────────────────
cat > /usr/local/bin/cloudcam-logs <<'LOGS'
#!/usr/bin/env bash
case "${1:-all}" in
  server)  journalctl -u cloudcam-server  -f --no-pager ;;
  gui)     journalctl -u cloudcam-gui     -f --no-pager ;;
  compute) journalctl -u cloudcam-compute -f --no-pager ;;
  ap)      journalctl -u hostapd -u dnsmasq -f --no-pager ;;
  all)     journalctl -u cloudcam-server -u cloudcam-gui \
                      -u cloudcam-compute -f --no-pager ;;
  *)       echo "Использование: cloudcam-logs [server|gui|compute|ap|all]" ;;
esac
LOGS
chmod +x /usr/local/bin/cloudcam-logs

# ── Avahi mDNS ────────────────────────────────────────────────────────────
mkdir -p /etc/avahi/services
cat > /etc/avahi/services/cloudcam.service <<AVAHI
<?xml version="1.0" standalone='no'?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
  <name replace-wildcards="yes">CloudCam on %h</name>
  <service>
    <type>_http._tcp</type>
    <port>80</port>
  </service>
</service-group>
AVAHI
systemctl enable avahi-daemon

# Финальные права
chown -R "${CLOUDCAM_USER}:${CLOUDCAM_USER}" "$INSTALL_DIR" "$DATA_DIR"
find "$INSTALL_DIR" -name "*.py" -exec chmod +x {} \; 2>/dev/null || true
find "$INSTALL_DIR" -name "*.sh" -exec chmod +x {} \; 2>/dev/null || true

# Запускаем то что можно сейчас
systemctl restart nginx       || warn "nginx: ошибка запуска"
systemctl restart avahi-daemon || true
# AP-сервисы и cloudcam-* стартуют после reboot

# =============================================================================
# ИТОГ
# =============================================================================
echo
echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${GREEN}║     ✓  CloudCam v5.0 успешно установлен!                 ║${NC}"
echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
echo
echo -e "  Wi-Fi AP     : ${BOLD}${AP_SSID}${NC}  (пароль: ${AP_PASS})"
echo -e "  Интерфейс   : ${BOLD}${AP_IFACE}${NC}  (MediaTek MT7612U)"
echo -e "  IP           : ${BOLD}${AP_IP}${NC}"
echo -e "  Веб-панель   : http://${AP_IP}/"
echo -e "  mDNS         : http://cloudcam.local/"
echo
echo -e "  Порядок старта AP:  dhcpcd → hostapd → dnsmasq → cloudcam-*"
echo
echo -e "  Команды:"
echo -e "    ${CYAN}cloudcam-status${NC}              — статус системы"
echo -e "    ${CYAN}cloudcam-calibrate [N=30]${NC}    — калибровка камер"
echo -e "    ${CYAN}cloudcam-logs [server|gui|ap]${NC} — логи"
echo
echo -e "  Флаг калибровки: ${YELLOW}${CAM_FLAG}${NC}  (переопределяется автоматически)"
echo
echo -e "  ${YELLOW}━━  ТРЕБУЕТСЯ ПЕРЕЗАГРУЗКА  ━━${NC}"
echo -e "    ${BOLD}sudo reboot${NC}"
echo
echo -e "  После reboot → подключитесь к '${AP_SSID}' → http://${AP_IP}/"
echo -e "  Затем калибровка: ${CYAN}sudo cloudcam-calibrate 30${NC}"
echo
echo -e "  Лог установки: ${LOG_FILE}"
echo