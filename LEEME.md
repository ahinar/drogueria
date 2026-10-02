# Sistema de droguería: Fase 0

Base del sistema: usuarios con roles, bitácora de auditoría inmutable y respaldos.
Funciona en la red local, sin internet.

## 1. Instalación (solo en el PC principal, una vez)

1. Instala **Python 3.11 o superior** desde python.org. En el instalador marca **"Add Python to PATH"**.
2. Copia esta carpeta al PC principal, por ejemplo en `C:\drogueria`.
3. Abre la carpeta, haz clic en la barra de direcciones, escribe `cmd` y pulsa Enter.
4. Ejecuta estos comandos, uno por uno:

```
python -m venv venv
venv\Scripts\pip install -r requirements.txt
```

## 2. Arrancar

Doble clic en `iniciar_servidor.bat`. Verás dos direcciones:

- En el mismo PC: `http://localhost:5000`
- Desde el otro PC: `http://192.168.x.x:5000` (la dirección exacta aparece en la ventana)

La primera vez el sistema pide crear el **administrador**. Después, desde **Usuarios**, crea los
demás usuarios (Director Técnico, Auxiliar).

Si Windows pregunta por el Firewall, permite el acceso en **redes privadas**.

## 3. Que arranque solo al encender el PC

1. Presiona `Win + R`, escribe `shell:startup` y pulsa Enter.
2. Copia ahí un acceso directo a `iniciar_servidor.bat`.

## 4. Respaldos

- El sistema hace un respaldo automático al iniciar si el último tiene más de 24 horas.
- También puedes crearlo desde **Respaldos** o con `hacer_respaldo.bat`.
- Para un respaldo diario a las 10 p. m. (ajusta la ruta), abre `cmd` como administrador:

```
schtasks /create /tn "Respaldo Drogueria" /tr "C:\drogueria\hacer_respaldo.bat" /sc daily /st 22:00
```

- Para copiar cada respaldo a una memoria USB o a una carpeta sincronizada con la nube, define la
  variable de entorno `DROGUERIA_BACKUP_EXTRA` con esa carpeta (ejemplo: `setx DROGUERIA_BACKUP_EXTRA "E:\respaldos"`).
- **Restaurar:** cierra el sistema, copia el respaldo que quieras sobre `db\drogueria.db` (renómbralo) y
  borra los archivos `drogueria.db-wal` y `drogueria.db-shm` si existen.

## 5. Recomendaciones

- Usa un **UPS** en el PC principal.
- Reserva una IP fija para ese PC en el router, para que la dirección no cambie.
- No expongas el puerto 5000 a internet.
- Guarda una copia de los respaldos fuera del local.

## 6. Pruebas (opcional)

```
venv\Scripts\python -m unittest discover -s tests -v
```

## Estructura

```
app/          código (rutas, base de datos, plantillas HTML)
static/       estilos y sonidos
db/           base de datos (drogueria.db)
backups/      respaldos
pdfs/         formatos y reportes en PDF (a partir de la Fase 1)
tests/        pruebas automáticas
```
