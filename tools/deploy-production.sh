#!/usr/bin/env bash
# Safe production update: preserves the customized index.html and server.py.

set -u

STAGE="/tmp/journal-release"
APP_ROOT="/var/www/journal"
STATIC_ROOT="$APP_ROOT/static"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="/var/backups/journal-$STAMP"

required=(
  "journal.py"
  "pdf_import.py"
  "static/app.js"
  "static/styles.css"
  "static/mobile.css"
  "static/practice-scales.js"
  "static/practice-scales.css"
)

for relative in "${required[@]}"; do
  if [ ! -s "$STAGE/$relative" ]; then
    echo "ОШИБКА: во временной папке нет $relative. Сайт не изменён."
    exit 1
  fi
done

before_code="$(curl -s --max-time 8 -o /dev/null -w '%{http_code}' http://127.0.0.1:8765/ || true)"
if [ "$before_code" != "200" ]; then
  echo "ОШИБКА: сайт до обновления не отвечает на порту 8765. Обновление отменено."
  exit 1
fi

if ! python3 -m py_compile "$STAGE/journal.py" "$STAGE/pdf_import.py"; then
  echo "ОШИБКА: проверка Python не прошла. Сайт не изменён."
  exit 1
fi
if ! grep -q "copy-table-btn" "$STAGE/static/app.js" ||
   ! grep -q "lesson-status-btn" "$STAGE/static/app.js" ||
   ! grep -q "practice-summary" "$STAGE/static/app.js"; then
  echo "ОШИБКА: загружена не та версия app.js. Сайт не изменён."
  exit 1
fi

mkdir -p "$BACKUP/static" "$BACKUP/data" || exit 1
if ! cp -a "$APP_ROOT/journal.py" "$APP_ROOT/pdf_import.py" "$BACKUP/" ||
   ! cp -a "$STATIC_ROOT/index.html" "$BACKUP/static/" ||
   ! cp -a "$STATIC_ROOT/app.js" "$STATIC_ROOT/styles.css" "$STATIC_ROOT/mobile.css" "$BACKUP/static/" ||
   ! cp -a "$STATIC_ROOT/practice-scales.js" "$STATIC_ROOT/practice-scales.css" "$BACKUP/static/"; then
  echo "ОШИБКА: резервная копия не создана. Сайт не изменён."
  exit 1
fi
if [ -f "$APP_ROOT/data/students.json" ]; then
  cp -a "$APP_ROOT/data/students.json" "$BACKUP/data/" || exit 1
fi

restore_files() {
  cp -a "$BACKUP/journal.py" "$BACKUP/pdf_import.py" "$APP_ROOT/"
  cp -a "$BACKUP/static/"* "$STATIC_ROOT/"
  if [ -f "$BACKUP/data/students.json" ]; then
    cp -a "$BACKUP/data/students.json" "$APP_ROOT/data/"
  fi
}

install_file() {
  local source="$1"
  local target="$2"
  install -m 0644 "$source" "$target.new" && mv -f "$target.new" "$target"
}

if ! install_file "$STAGE/journal.py" "$APP_ROOT/journal.py" ||
   ! install_file "$STAGE/pdf_import.py" "$APP_ROOT/pdf_import.py" ||
   ! install_file "$STAGE/static/app.js" "$STATIC_ROOT/app.js" ||
   ! install_file "$STAGE/static/styles.css" "$STATIC_ROOT/styles.css" ||
   ! install_file "$STAGE/static/mobile.css" "$STATIC_ROOT/mobile.css" ||
   ! install_file "$STAGE/static/practice-scales.js" "$STATIC_ROOT/practice-scales.js" ||
   ! install_file "$STAGE/static/practice-scales.css" "$STATIC_ROOT/practice-scales.css"; then
  restore_files
  echo "ОШИБКА: файлы не установлены. Восстановлена прежняя версия."
  exit 1
fi

if ! python3 - "$STATIC_ROOT/index.html" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")

if 'id="copy-table-btn"' not in text:
    anchor = '            <button id="settings-btn" class="secondary-btn hidden" type="button">Настройки</button>'
    buttons = (
        '            <button id="copy-table-btn" class="secondary-btn hidden" '
        'type="button">Копировать таблицу</button>\n'
        '            <button id="paste-table-btn" class="secondary-btn hidden" '
        'type="button" disabled>Вставить таблицу</button>\n'
    )
    if anchor not in text:
        raise SystemExit("Не найдено место для кнопок в index.html")
    text = text.replace(anchor, buttons + anchor, 1)

replacements = {
    r'styles\.css(?:\?v=[^"]*)?': 'styles.css?v=table-tools2',
    r'mobile\.css(?:\?v=[^"]*)?': 'mobile.css?v=table-tools2',
    r'app\.js(?:\?v=[^"]*)?': 'app.js?v=table-tools2',
    r'practice-scales\.css(?:\?v=[^"]*)?': 'practice-scales.css?v=2',
    r'practice-scales\.js(?:\?v=[^"]*)?': 'practice-scales.js?v=2',
}
for pattern, replacement in replacements.items():
    text = re.sub(pattern, replacement, text)

path.write_text(text, encoding="utf-8")
PY
then
  restore_files
  echo "ОШИБКА: шапка сайта не обновлена. Восстановлена прежняя версия."
  exit 1
fi

restart_on_8765() {
  systemctl stop journal
  pkill -9 -f '/var/www/journal/.venv/bin/python.*server.py' || true
  fuser -k 8765/tcp 8766/tcp 8767/tcp || true
  echo "Порт освобождается. Ждите 75 секунд и ничего не нажимайте."
  sleep 75
  systemctl start journal
  sleep 6
}

restart_on_8765

local_code="$(curl -s --max-time 8 -o /dev/null -w '%{http_code}' http://127.0.0.1:8765/ || true)"
app_marker="$(curl -s --max-time 8 http://127.0.0.1:8765/app.js | grep -c 'copy-table-btn' || true)"
index_marker="$(curl -s --max-time 8 http://127.0.0.1:8765/ | grep -c 'table-tools2' || true)"
api_marker="$(curl -s --max-time 8 http://127.0.0.1:8765/api/students | grep -c 'lessonStatus' || true)"

if [ "$local_code" != "200" ] || [ "$app_marker" = "0" ] || [ "$index_marker" = "0" ] || [ "$api_marker" = "0" ]; then
  echo "ПРОВЕРКА НЕ ПРОШЛА. ВОССТАНАВЛИВАЮ ПРЕЖНЮЮ ВЕРСИЮ."
  restore_files
  restart_on_8765
  rollback_code="$(curl -s --max-time 8 -o /dev/null -w '%{http_code}' http://127.0.0.1:8765/ || true)"
  echo "ОТКАТ ЗАВЕРШЁН. python8765:$rollback_code"
  exit 1
fi

python_8766="$(curl -s --max-time 3 -o /dev/null -w '%{http_code}' http://127.0.0.1:8766/ || true)"
site_code="$(curl -s --max-time 10 -o /dev/null -w '%{http_code}' https://rusklasst.ru/ || true)"

echo "ГОТОВО. ВСЕ ИЗМЕНЕНИЯ УСТАНОВЛЕНЫ."
echo "Резервная копия: $BACKUP"
echo "python8765:$local_code"
echo "python8766:$python_8766"
echo "site:$site_code"
