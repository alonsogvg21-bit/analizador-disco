# Analizador de disco

Herramienta para Windows y Linux que muestra qué ocupa espacio en el disco y
ayuda a encontrar archivos basura. Tiene tres interfaces sobre el mismo motor:

- **Aplicación de escritorio** (la principal): `python main.py`
- **Terminal**: `python main.py cli ...`
- **Web local** (opcional): `python main.py web`

Por defecto **solo lee**. Lo único que modifica el disco es la limpieza, que
siempre muestra la lista exacta, pide confirmación y envía a la papelera.

## Requisitos

- Python 3.10 o superior.
- Las bibliotecas de `requirements.txt`: psutil, send2trash, PySide6-Essentials,
  flask, fpdf2 y pytest. Si solo vas a usar la terminal o la web, PySide6 no es
  imprescindible; si solo usas el escritorio, flask tampoco.
- Opcional, solo para la salud de los discos: el programa `smartctl`
  (smartmontools). Ver la sección [Salud de los discos](#salud-de-los-discos-smart).

## Instalación

**Windows (PowerShell)**

```powershell
cd analizador-disco
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**Linux**

```bash
cd analizador-disco
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

El entorno virtual (`.venv`) es opcional pero recomendable. En Linux usa
`python3` en lugar de `python` en los ejemplos que siguen.

## Aplicación de escritorio

```
python main.py
```

Se abre una ventana con una barra lateral:

| Sección | Qué hay |
|---|---|
| **Inicio** | Una tarjeta por disco con su barra de uso (verde, amarilla o roja) y el botón **Escanear** |
| **Explorar espacio** | Cuatro pestañas: mapa de bloques, árbol de carpetas, tipos de archivo y tabla de archivos |
| **Archivos basura** | Categorías con casillas, contador de espacio a liberar y envío a la papelera |
| **Duplicados** | Grupos de archivos idénticos; el original de cada grupo no se puede marcar |
| **Historial** | Gráfica de uso en el tiempo y comparación entre dos escaneos |
| **Salud del disco** | Tarjeta SMART por disco, con semáforo, medidores y autopruebas |
| **Configuración** | Tema claro u oscuro, duplicados al escanear y alertas de salud |

- **Escaneo**: corre en segundo plano. La barra inferior muestra el avance y un
  botón **Cancelar** (también vale la tecla Esc). La ventana no se congela.
- **Mapa de bloques**: cada bloque es una carpeta o un archivo y su área es
  proporcional al tamaño. El color indica el tipo (leyenda debajo). Al pasar el
  ratón aparecen nombre, tamaño y porcentaje respecto a la carpeta padre. Clic en
  una carpeta para entrar; la ruta de arriba (`Downloads › Haskell`) sirve para
  volver. Se cargan dos niveles cada vez, para que funcione en discos grandes.
- **Tabla de archivos**: pulsa «Tamaño», «Modificado» o «Último acceso» para
  ordenar; filtra por tipo y tamaño mínimo.
- **Clic derecho** sobre cualquier archivo o carpeta: abrir ubicación, copiar
  ruta, mover o enviar a la papelera.
- **Mover o borrar**: siempre aparece una ventana con la lista exacta, el
  espacio y la casilla **Solo simular**. El botón predeterminado es Cancelar.
  Las carpetas del sistema no se pueden mover ni borrar.

El treemap se dibuja con QPainter. Los rectángulos los calcula
`desktop/squarify.py` con el algoritmo *squarified*, que no depende de Qt y se
prueba con `tests/test_squarify.py`.

## Interfaz web (opcional)

```
python main.py web
```

(`python main.py gui` sigue funcionando como sinónimo.)
Se abre `http://127.0.0.1:5000` en el navegador. Opciones: `--puerto 5050` y
`--no-abrir`. Si el puerto está ocupado se usa el siguiente libre. Para cerrar,
pulsa `Ctrl+C` en la terminal.

1. Elige un disco o una carpeta y pulsa **Escanear**.
2. Revisa las pestañas **Qué ocupa espacio**, **Mapa de bloques**, **Archivos**,
   **Archivos basura** e **Historial**.
3. En **Archivos** o en **Archivos basura**, marca lo que quieras y pulsa
   **Mover a otra carpeta…** o **Enviar a la papelera…**. Aparece una ventana
   con la lista exacta, donde puedes confirmar, cancelar o marcar **Solo simular**.
4. Descarga el reporte en HTML, CSV o PDF con los botones de la parte superior.

### Pestaña Archivos: orden y filtros

- Pulsa el título **Tamaño**, **Modificado** o **Último acceso** para ordenar
  por esa columna; púlsalo otra vez para invertir el orden.
- Filtra por **tipo** de archivo y por **tamaño mínimo** en MB.
- La selección se conserva al cambiar de orden, de filtro o de pestaña.

### Pestaña Historial

- **Uso a lo largo del tiempo**: gráfica de línea con lo que ocupaba la carpeta
  en cada escaneo guardado. Cada escaneo que termina en la web se guarda solo.
- **Comparar dos fechas**: elige dos escaneos y verás qué carpetas crecieron o
  disminuyeron y cuántos MB.
- **Escaneos programados**: crea o quita un escaneo periódico de la carpeta.

### Mapa de bloques

La pestaña **Mapa de bloques** dibuja la carpeta escaneada como un mosaico, al
estilo de WinDirStat: cada bloque es una carpeta o un archivo y su área es
proporcional al espacio que ocupa.

- **Entrar en una carpeta**: pulsa su bloque o su nombre. El mapa muestra su
  contenido.
- **Volver**: usa la ruta de navegación que hay sobre el mapa
  (por ejemplo `Downloads › Haskell › hola`).
- **Colores**: cada tipo de archivo tiene un color, con la leyenda debajo del
  mapa. Una carpeta toma el color del tipo que más espacio ocupa dentro de ella
  y lleva una esquina marcada para distinguirla de un archivo.
- **Detalles**: al pasar el ratón por un bloque (o llegar a él con el teclado)
  aparecen su nombre, su tamaño y el porcentaje respecto a su carpeta padre.

Para que sea rápido en discos grandes, el mapa pide al servidor solo dos
niveles cada vez y, en cada carpeta, los 30 elementos más grandes; el resto se
suma en un bloque «elementos más pequeños».

Los datos salen de `core/arbol.py`, que reutiliza el escaneo ya hecho:

```python
from core.escaner import escanear
from core.arbol import arbol_json

resultado = escanear("C:/Users/ana/Downloads")
arbol = arbol_json(resultado, niveles=2)          # diccionario listo para json.dumps
sub = arbol_json(resultado, arbol["hijos"][0]["ruta"], niveles=3, max_hijos=10)
```

`niveles` admite de 1 a 3. La web lo expone en `/api/arbol?ruta=...&niveles=2`.

La posición de los bloques la calcula
[d3-hierarchy](https://d3js.org/d3-hierarchy) 3.1.2 (licencia ISC), guardada en
`web/static/vendor/d3-hierarchy.min.js`. No se carga nada de internet.

## Terminal

```
python main.py cli --help
python main.py cli <comando> --help
```

| Comando | Qué hace |
|---|---|
| `resumen` | Espacio total, usado y libre de cada disco |
| `carpetas RUTA` | Carpetas de mayor a menor (`--profundidad`, `--limite`) |
| `top RUTA` | Lista de archivos con orden y filtros (`--orden`, `--ascendente`, `--tipo`, `--min-mb`, `-n`) |
| `tipos RUTA` | Espacio por tipo de archivo |
| `basura [RUTA]` | Basura por categorías; sin RUTA revisa solo temporales, caché y papelera |
| `duplicados RUTA` | Archivos idénticos (`--min-mb`) |
| `reporte RUTA` | Reporte en HTML, CSV y PDF (`--salida`, `--formato html\|csv\|pdf\|ambos\|todos`) |
| `limpiar [RUTA] -c LISTA` | Envía basura a la papelera, con confirmación (`--dry-run` para simular) |
| `mover RUTA -d CARPETA` | Mueve archivos a otra carpeta o disco, con confirmación (`--dry-run`) |
| `guardar RUTA` | Escanea y guarda el resultado en el historial |
| `historial [RUTA]` | Lista los escaneos guardados |
| `comparar RUTA` | Compara dos escaneos guardados (`--desde`, `--hasta`) |
| `programar crear\|listar\|quitar` | Escaneos periódicos con el programador del sistema |
| `salud [ver\|prueba\|revisar\|alertas\|programar]` | Salud de los discos con SMART |

**Ejemplos en Windows**

```powershell
python main.py cli resumen
python main.py cli carpetas C:\Users\ana --profundidad 2
python main.py cli top D:\ -n 20
python main.py cli basura $HOME\Documents --sin-duplicados
python main.py cli reporte $HOME\Downloads --salida $HOME\Desktop
python main.py cli limpiar -c temporales,cache --dry-run
python main.py cli limpiar $HOME\proyectos -c regenerables
```

**Ejemplos en Linux**

```bash
python3 main.py cli resumen
python3 main.py cli carpetas ~ --profundidad 2
python3 main.py cli top /home -n 20
python3 main.py cli basura ~/Documentos --sin-duplicados
python3 main.py cli reporte ~/Descargas --salida ~/Escritorio
python3 main.py cli limpiar -c temporales,cache --dry-run
python3 main.py cli limpiar ~/proyectos -c regenerables
```

### Limpiar desde la terminal

`--categorias` (o `-c`) es obligatorio y acepta: `temporales`, `cache`,
`regenerables`, `duplicados`, `antiguos`. Las tres últimas necesitan una RUTA.

El comando muestra todos los elementos y el espacio a liberar. Con `--dry-run`
termina ahí. Sin él, pide escribir `ELIMINAR`; cualquier otra respuesta cancela.

### Ordenar y filtrar archivos

```
python main.py cli top RUTA --orden accedido --ascendente
python main.py cli top RUTA --tipo videos,imagenes --min-mb 500 -n 20
```

`--orden` admite `tamano` (por defecto), `modificado` y `accedido`. Sin
`--ascendente` salen primero los más grandes o los más recientes.
`--tipo` admite: videos, imagenes, documentos, comprimidos, instaladores,
codigo, otros.

### Mover archivos

```
python main.py cli mover RUTA --destino CARPETA --tipo videos --min-mb 500 --dry-run
python main.py cli mover RUTA --destino CARPETA -c duplicados
```

Hay que indicar qué mover: por filtros (`--tipo`, `--min-mb`) o por categoría de
basura (`-c regenerables,duplicados,antiguos`). El comando muestra la lista
exacta; con `--dry-run` termina ahí, y sin él pide escribir `MOVER`.

- La carpeta de destino debe existir y no puede ser una carpeta del sistema.
- Nunca se sobrescribe: si el nombre ya existe en el destino se guarda como
  `nombre (1).ext`.
- Antes de empezar se comprueba que en el destino hay espacio suficiente.

### Comparar escaneos

```
python main.py cli guardar RUTA
python main.py cli historial
python main.py cli comparar RUTA
python main.py cli comparar RUTA --desde 2026-09-01 --hasta 2026-10-01
```

`comparar` sin fechas usa los dos últimos escaneos; con fechas, el escaneo más
cercano a cada una. Muestra qué carpetas crecieron o disminuyeron y cuántos MB
(`--min-mb` descarta cambios pequeños; por defecto 1 MB).

El historial es una base de datos SQLite en
`%LOCALAPPDATA%\analizador-disco\historial.db` (Windows) o
`~/.local/share/analizador-disco/historial.db` (Linux). Se guarda el total y el
tamaño de las carpetas de los tres primeros niveles. Para usar otra carpeta,
define la variable de entorno `ANALIZADOR_DISCO_DATOS`.

### Escaneos programados

```
python main.py cli programar crear RUTA --frecuencia diaria --hora 09:00
python main.py cli programar listar
python main.py cli programar quitar NOMBRE
```

`--frecuencia` admite `diaria` y `semanal` (cada lunes). La tarea ejecuta
`guardar RUTA`, así que cada escaneo queda en el historial.

- **Windows**: se crea con `schtasks` en la carpeta `AnalizadorDisco` del
  Programador de tareas. Se ejecuta con tu usuario y tu sesión iniciada.
- **Linux**: se añade una línea a tu `crontab`, marcada con un comentario; el
  resto del crontab no se toca.

Si mueves la carpeta del programa, quita las tareas y vuelve a crearlas.

### Discos de red

Se aceptan rutas de discos de red **ya montados**: rutas UNC en Windows
(`\\servidor\recurso\carpeta`) o letras de unidad conectadas, y carpetas
montadas por NFS, SMB o SSHFS en Linux. El programa avisa de que el escaneo
puede ser lento.

En un disco de red no hay papelera, y "enviar a la papelera" allí borraría para
siempre. Por eso el programa lo rechaza; sí se puede mover a otra carpeta.

### Reporte en PDF

```
python main.py cli reporte RUTA --formato pdf
python main.py cli reporte RUTA --formato todos
```

El PDF incluye el resumen, gráficas de barras de discos, tipos y carpetas, los
25 archivos más pesados y el resumen de basura. `--formato ambos` (por defecto)
sigue generando HTML y CSV; `todos` añade el PDF.

## Salud de los discos (SMART)

Todo este módulo es de **solo lectura**: consulta lo que el disco informa sobre
sí mismo y nunca escribe datos en él.

### Qué hace falta

1. Instalar **smartmontools** (el programa `smartctl`):
   - Windows: `winget install smartmontools.smartmontools` y volver a abrir la terminal.
   - Debian / Ubuntu: `sudo apt install smartmontools`
   - Fedora: `sudo dnf install smartmontools` · Arch: `sudo pacman -S smartmontools`
2. Ejecutar con **permisos de administrador**, que es lo que exige el sistema
   para hablar directamente con el disco:
   - Windows: abre PowerShell con clic derecho > *Ejecutar como administrador*.
   - Linux: antepón `sudo` (`sudo python3 main.py cli salud`).

Si falta `smartctl` o los permisos, el programa lo dice y muestra estos pasos.

### Uso

```
python main.py cli salud                         # estado de todos los discos
python main.py cli salud prueba /dev/sda         # autoprueba corta (unos 2 minutos)
python main.py cli salud prueba /dev/sda --tipo larga
python main.py cli salud revisar                 # estado + alertas si algo empeoró
python main.py cli salud alertas                 # ver la configuración de alertas
python main.py cli salud programar --hora 09:00  # revisión diaria automática
```

Los nombres de disco (`/dev/sda`, `/dev/nvme0`...) son los que muestra
`salud`, también en Windows. En la web, la sección **Salud de los discos**
tiene una tarjeta por disco con semáforo, medidores de temperatura y de vida
restante, botones de autoprueba y el botón **Actualizar**.

### Cómo funciona SMART

SMART es un sistema de autodiagnóstico que llevan los propios discos. El disco
va anotando contadores sobre su funcionamiento y `smartctl` se los pide. Este
programa ejecuta `smartctl --json -a DISCO` y traduce la respuesta.

| Valor | Qué significa | Qué mirar |
|---|---|---|
| Modelo, firmware, interfaz | Identificación del disco y cómo está conectado (SATA, NVMe) | Informativo |
| Temperatura | Grados del disco ahora mismo | Lo normal es 25–50 °C; los NVMe trabajan más calientes |
| Horas de uso | Tiempo total encendido | Informativo: muchas horas no implican fallo |
| Ciclos de encendido | Veces que se ha encendido | Informativo |
| Sectores reasignados | Zonas dañadas que el disco sustituyó por otras de reserva | Debe ser 0. Si crece, el disco se está degradando |
| Sectores pendientes | Zonas dudosas que aún no se han podido sustituir | Debe ser 0. Es la señal más temprana de fallo |
| Sectores incorregibles | Zonas que no se pudieron leer ni corregir | Debe ser 0. Puede haber datos perdidos |
| Errores de medio (NVMe) | Lecturas o escrituras que fallaron sin poder corregirse | Debe ser 0 |
| Vida restante (SSD) | Desgaste estimado por el fabricante; 100 % = nuevo | Los SSD admiten un número limitado de escrituras |
| Estado SMART | Veredicto del propio disco: correcto o fallo | "Fallo" significa avería inminente |

SMART no lo detecta todo: un disco puede fallar de golpe con todos los valores
en orden. Un estado "Bueno" no sustituye a tener copia de seguridad.

### Estado general

Las reglas están en `evaluar_estado()` de `core/salud.py`.

| Estado | Cuándo |
|---|---|
| **Malo** | El disco declara fallo SMART · algún atributo está bajo su umbral de fallo · un NVMe tiene un aviso crítico · la última autoprueba terminó con error · a un SSD le queda un 5 % de vida o menos |
| **Precaución** | Sectores reasignados, pendientes o incorregibles mayores que 0 · errores de medio en NVMe · a un SSD le queda un 20 % de vida o menos · la temperatura alcanza el límite |
| **Bueno** | Nada de lo anterior |
| **Sin datos** | Faltan permisos, o el disco no ofrece SMART (memorias USB, algunas cajas externas) |

Con **Malo**, copia tus datos cuanto antes y cambia el disco. Con
**Precaución**, ten copia de seguridad y vigila si los contadores suben.

### Autopruebas

Es el propio disco el que se examina: lee su superficie y comprueba su
electrónica. **No escribe ni modifica tus datos** y puedes seguir usando el
equipo. La corta dura unos 2 minutos; la larga recorre todo el disco y puede
tardar horas. El resultado aparece al volver a consultar la salud.

### Alertas

Se avisa cuando un disco **pasa** a Precaución o Malo, o cuando su temperatura
alcanza el límite. Solo se avisa de los cambios: un disco que sigue igual no
repite el aviso.

```
python main.py cli salud alertas --temperatura 50
python main.py cli salud alertas --escritorio si --probar
python main.py cli salud alertas --correo si --smtp-servidor smtp.ejemplo.com --smtp-puerto 587 --smtp-usuario ana --correo-de ana@ejemplo.com --correo-para ana@ejemplo.com
```

- **Límite de temperatura**: por defecto automático (55 °C en discos SATA,
  70 °C en NVMe). `--temperatura auto` vuelve a ese valor.
- **Escritorio**: notificación de Windows, o `notify-send` en Linux.
- **Correo**: por SMTP con cifrado STARTTLS. La contraseña **no se guarda en
  ningún archivo**; se lee de la variable de entorno
  `ANALIZADOR_DISCO_SMTP_CLAVE`.
- Las alertas se envían al ejecutar `salud revisar` o al pulsar **Actualizar**
  en la web. Para que lleguen solas, usa `salud programar` desde una terminal
  de administrador (Windows) o con `sudo` (Linux). Se quita con
  `programar quitar salud-discos`.

## Categorías de basura

| Categoría | Qué es | ¿Se puede limpiar? |
|---|---|---|
| Temporales | Archivos de trabajo de los programas | Sí, salvo los modificados en las últimas 24 horas |
| Caché | Copias de navegadores y aplicaciones | Sí (cierra antes el navegador) |
| Carpetas regenerables | `node_modules`, `__pycache__`, `.gradle`, `.venv` | Sí |
| Duplicados | Copias idénticas; se conserva la más antigua | Sí |
| Sin abrir hace más de un año | Archivos grandes sin uso reciente | Sí, revisándolos antes |
| Papelera, Descargas, Registros | Se muestra cuánto ocupan | No, solo informativo |

Ubicaciones revisadas:

- **Windows**: `%TEMP%`, `C:\Windows\Temp`, `Prefetch`, caché de Chrome, Edge y
  Firefox, papelera de cada disco y carpeta de descargas.
- **Linux**: `/tmp`, `/var/tmp`, `~/.cache`, `~/.local/share/Trash`, caché de
  apt, `/var/log` y el journal de systemd.

## Seguridad

- Nada se borra definitivamente: todo va a la papelera (send2trash).
- Mover tampoco destruye nada: no sobrescribe y, si una carpeta solo se pudo
  mover en parte, deja lo que falta en su sitio y lo avisa.
- Carpetas bloqueadas siempre: en Windows `C:\Windows` y `Program Files`; en
  Linux `/bin`, `/boot`, `/dev`, `/etc`, `/lib`, `/proc`, `/sbin`, `/sys` y
  `/usr`. También la raíz de cada disco y la carpeta personal completa.
- Los archivos en uso o sin permisos se omiten y se informa de ello.
- La web escucha solo en `127.0.0.1` y exige un token interno para escanear o
  limpiar, así que otra página abierta en el navegador no puede dar órdenes.
- La web solo acepta mover o limpiar elementos que ella misma encontró en el
  último escaneo, nunca rutas arbitrarias.

## Limitaciones

- "Sin abrir hace más de un año" usa la fecha más reciente entre último acceso
  y modificación. Windows a menudo no actualiza el último acceso, así que es
  una aproximación.
- Los archivos de OneDrive que están solo en la nube no se cuentan: no ocupan
  disco y leerlos los descargaría.
- No se siguen enlaces simbólicos ni enlaces de carpeta de Windows.
- El espacio enviado a la papelera no vuelve al disco hasta vaciarla.
- Tras mover o limpiar, los tamaños de carpetas, tipos y mapa siguen siendo los
  del último escaneo hasta que se vuelve a escanear.
- El PDF usa fuentes que solo admiten caracteres latinos: en nombres de archivo
  con otros alfabetos esos caracteres salen como `?`.
- En Linux, los temporales de otros usuarios y las cachés del sistema requieren
  administrador; el programa los muestra pero no los limpia.

## Estructura

```
main.py      Punto de entrada (sin argumentos: escritorio; cli; web)
desktop/     Aplicación de escritorio (PySide6): ventana, vistas, treemap, gráficas,
             hilos y estilos
core/        Motor: escaneo, carpetas, árbol, tipos, consulta, duplicados, basura,
             reporte (HTML, CSV, PDF), limpieza, mover, historial, programador,
             salud (SMART) y alertas
core/reglas/ Ubicaciones conocidas de Windows y de Linux
cli/         Terminal (argparse)
web/         Interfaz web (Flask, HTML, CSS y JavaScript; d3-hierarchy en static/vendor)
utils/       Formato, detección del sistema, discos de red y carpetas protegidas
tests/       Pruebas con pytest
```

Solo `core/limpieza.py` y `core/mover.py` modifican tus archivos.
`core/programador.py` crea o quita la tarea programada y `core/historial.py`
escribe en la base de datos del propio programa.

## Pruebas

```
python -m pytest -q
```

Las pruebas trabajan en carpetas temporales y no usan la papelera real, ni el
programador de tareas, ni tu historial, ni tus discos, ni abren ventanas (la
aplicación de escritorio se prueba sin pantalla): la salud se prueba con
salidas de ejemplo de `smartctl` guardadas en `tests/datos_smart/`. Para
probar también la papelera de verdad (deja un archivo de 10 bytes en ella):

```powershell
$env:PROBAR_PAPELERA = "1"; python -m pytest tests/test_limpieza.py
```

```bash
PROBAR_PAPELERA=1 python3 -m pytest tests/test_limpieza.py
```
