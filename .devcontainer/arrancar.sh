#!/usr/bin/env bash
# =====================================================================
# Arranca el programa con datos de DEMOSTRACIÓN (para Codespaces).
#   - Usa la base db/demo.db (nunca la real: db/drogueria.db).
#   - Si la demo no existe, la crea con scripts/crear_demo.py.
#   - Prende el servidor en segundo plano en el puerto 5000.
#   - Lo que imprime el servidor queda en /tmp/fervifarma.log
# =====================================================================
set -e
cd "$(dirname "$0")/.."                      # carpeta del proyecto

export TZ="America/Bogota"                   # hora de Colombia (Codespaces viene en UTC)
export DROGUERIA_DB="$PWD/db/demo.db"        # base de demostración
export DROGUERIA_BACKUPS="$PWD/backups/demo" # sus respaldos van aparte
mkdir -p db "$DROGUERIA_BACKUPS"

python scripts/crear_demo.py

# Si ya estaba prendido (por ejemplo al reconectar), no se prende dos veces.
# Guardamos el número del proceso (PID) en un archivo para reconocerlo.
PIDFILE=/tmp/fervifarma.pid
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "El servidor ya estaba encendido."
  exit 0
fi

# setsid + nohup: el servidor sigue vivo aunque termine este script
setsid nohup python run.py > /tmp/fervifarma.log 2>&1 < /dev/null &
echo $! > "$PIDFILE"
sleep 3
echo "Servidor encendido. Ábrelo desde la pestaña PORTS (puerto 5000)."
