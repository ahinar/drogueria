# Probar el programa en la nube (GitHub Codespaces)

Sirve para probar el programa **sin el PC de la droguería**, por ejemplo desde el celular.
GitHub presta un computador en la nube, instala todo y prende el programa con
**datos de demostración** (inventados). Tu base de datos real **nunca** se sube a GitHub.

## Usuarios de prueba

| Usuario | Rol | Contraseña |
|---|---|---|
| `admin` | Administrador | `Demo1234!` |
| `dt` | Director técnico | `Demo1234!` |
| `aux` | Auxiliar | `Demo1234!` |

La demo trae 12 productos con usos/síntomas, 2 proveedores, compras aprobadas,
un lote por vencer, un lote vencido, una recepción en cuarentena y $300.000 en caja menor.
Acetaminofén e Ibuprofeno se venden por tableta, sobre x 10 y (el acetaminofén) caja x 100.

## Pasos (desde el celular)

1. Abre **github.com/ahinar/drogueria** en el navegador del celular (Chrome o Safari),
   no en la app de GitHub, y entra con tu cuenta.
   Si no ves las opciones del paso 2, activa "Versión para computador" en el navegador.
2. Toca el botón verde **`<> Code`** → pestaña **Codespaces** → **Create codespace on main**.
3. Espera. La primera vez tarda unos minutos mientras instala todo.
4. Cuando termine aparece el aviso **"Your application running on port 5000 is available"** →
   toca **Open in Browser**.
   Si no lo ves: abre la pestaña **PORTS**, busca el puerto **5000 · Fervifarma (demo)**
   y toca el ícono del globo 🌐.
5. Entra con `admin` / `Demo1234!` y prueba.

El enlace es **privado**: solo funciona con tu cuenta de GitHub.

## Para volver otro día

- Entra a **github.com/codespaces** y abre el que ya creaste. Lo que hayas hecho en la demo sigue ahí.
- El programa se vuelve a prender solo al abrirlo.

## Cuidar las horas gratis

- La cuenta gratuita de GitHub incluye **120 horas-núcleo al mes** (con esta máquina de 2 núcleos,
  unas **60 horas reales**) y 15 GB de almacenamiento.
- El Codespace se apaga solo cuando no lo usas un rato, pero lo mejor es **detenerlo** al terminar
  (github.com/codespaces → `···` → **Stop codespace**).
- Si ya no lo necesitas, **bórralo** (`···` → **Delete**): el almacenamiento también cuenta.
- Revisa en tu cuenta de GitHub, sección de facturación (Billing), que Codespaces tenga un
  presupuesto de **$0** para que nunca te cobren si se acaban las horas.

## Si algo falla

- Abre la terminal del Codespace y escribe `cat /tmp/fervifarma.log` para ver los mensajes del programa.
- **Para actualizar el programa** (después de que Claude sube cambios a GitHub):
  `git pull && bash .devcontainer/reiniciar.sh`
- **Para empezar la demo desde cero** (borra los datos de prueba y crea unos nuevos):
  `bash .devcontainer/reiniciar.sh nueva`
- Para solo volver a prender el programa: `bash .devcontainer/reiniciar.sh`
- No borres `db/demo.db` a mano con el programa prendido: usa `reiniciar.sh nueva`, que lo
  apaga primero y borra también sus archivos temporales (`demo.db-wal` y `demo.db-shm`).

## Cómo funciona por dentro (para aprender)

- `.devcontainer/devcontainer.json` le dice a GitHub qué computador preparar (Python 3.12),
  qué instalar (`requirements.txt`), en qué hora trabajar (Colombia) y qué puerto mostrar (5000).
- `.devcontainer/arrancar.sh` crea la demo y prende el servidor cada vez que el Codespace arranca;
  espera a que el programa conteste y, si no contesta, muestra el error.
- `.devcontainer/reiniciar.sh` apaga el programa, espera a que se cierre de verdad, y lo vuelve a prender
  (con `nueva`, además crea la demo de cero).
- `scripts/crear_demo.py` llena la base de demostración. Por seguridad, se niega a escribir en la base real.
