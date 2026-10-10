#!/usr/bin/env bash
# =====================================================================
# REINICIAR el programa en Codespaces (un solo comando, sin carreras).
#
#   bash .devcontainer/reiniciar.sh          -> apaga y vuelve a prender
#                                               (la demo se conserva)
#   bash .devcontainer/reiniciar.sh nueva    -> además BORRA la demo y la
#                                               crea de cero (datos nuevos)
#
# ¿Por qué existe? Antes se hacía "kill ... && bash arrancar.sh", pero el
# programa viejo tarda un momento en cerrarse: arrancar.sh lo veía todavía
# vivo, creía que estaba encendido y no prendía nada. Y si se borraba
# demo.db con el programa prendido, quedaban sus archivos temporales
# (demo.db-wal y demo.db-shm) que dañan la base nueva.
# =====================================================================
cd "$(dirname "$0")/.."                      # carpeta del proyecto
PIDFILE=/tmp/fervifarma.pid

# ---- 1. Apagar el programa y ESPERAR a que de verdad se cierre ----
echo "Apagando el programa..."
if [ -f "$PIDFILE" ]; then kill "$(cat "$PIDFILE")" 2>/dev/null; fi
pkill -f "python run.py" 2>/dev/null          # por si quedó alguno sin PID guardado
for i in $(seq 1 20); do                      # hasta 10 segundos
  pgrep -f "python run.py" >/dev/null || break
  sleep 0.5
done
pkill -9 -f "python run.py" 2>/dev/null       # si no quiso cerrar, a la fuerza
rm -f "$PIDFILE"

# ---- 2. ¿Demo nueva? Se borra la base Y sus archivos temporales ----
if [ "$1" = "nueva" ]; then
  echo "Borrando la demo para crearla de cero..."
  rm -f db/demo.db db/demo.db-wal db/demo.db-shm
fi

# ---- 3. Prender (arrancar.sh crea la demo si no existe) ----
bash .devcontainer/arrancar.sh
