#!/usr/bin/env bash
# Safe production update: preserves the customized index.html and server.py.
#
# If this file was copied from Windows, bash will fail with `$'\r': command not found`.
# In that case run the Python installer instead — python3 accepts CRLF:
#   python3 /tmp/journal-release/tools/deploy-production.py

set -u

HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [ -f "$HERE/deploy-production.py" ]; then
  exec python3 "$HERE/deploy-production.py" "$@"
fi

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
  "static/practice-page.js"
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
   ! grep -q "practice-summary" "$STAGE/static/app.js" ||
   ! grep -q "restorePracticeScroll" "$STAGE/static/app.js" ||
   ! grep -q "keepScroll" "$STAGE/static/app.js" ||
   ! grep -q "applyCopiedTable" "$STAGE/static/app.js" ||
   ! grep -q "bumpSaveEpoch" "$STAGE/static/app.js"; then
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
   ! install_file "$STAGE/static/practice-scales.css" "$STATIC_ROOT/practice-scales.css" ||
   ! install_file "$STAGE/static/practice-page.js" "$STATIC_ROOT/practice-page.js"; then
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

replacements = {
    r'styles\.css(?:\?v=[^"]*)?': 'styles.css?v=table-tools3',
    r'mobile\.css(?:\?v=[^"]*)?': 'mobile.css?v=keep-scroll2',
    r'app\.js(?:\?v=[^"]*)?': 'app.js?v=table-copy2',
    r'practice-page\.js(?:\?v=[^"]*)?': 'practice-page.js?v=2',
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
app_marker="$(curl -s --max-time 8 http://127.0.0.1:8765/app.js | grep -c 'restorePracticeScroll' || true)"
index_marker="$(curl -s --max-time 8 http://127.0.0.1:8765/ | grep -c 'table-copy2' || true)"
api_code="$(curl -s --max-time 8 -o /dev/null -w '%{http_code}' http://127.0.0.1:8765/api/students || true)"

echo "Проверка: site=$local_code app=$app_marker index=$index_marker api=$api_code"

if [ "$local_code" != "200" ] || [ "$app_marker" = "0" ] || [ "$index_marker" = "0" ]; then
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
