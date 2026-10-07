# Pruebas manuales antes de publicar una versión

Las pruebas automáticas (`python -m pytest`) cubren el motor y la lógica de las
interfaces, pero no sustituyen a instalar el programa en un equipo real. Esta
lista se repasa en **equipos limpios**, es decir, sin Python ni herramientas
de desarrollo: una máquina virtual recién instalada es lo ideal.

Marca cada casilla en los tres sistemas:

- **Windows 10** (22H2, 64 bits)
- **Windows 11** (64 bits)
- **Ubuntu 22.04 o 24.04** (escritorio)

Anota la versión probada, la fecha y quién lo hizo. Si algo falla, copia el
detalle técnico desde la ventana de error y el contenido de `registro.log`.

## 0. Antes de empezar

- [ ] El equipo no tiene Python instalado (`python --version` no existe).
- [ ] Los archivos descargados coinciden con `SHA256SUMS-*.txt`:
  - Windows (PowerShell): `Get-FileHash .\AnalizadorDisco-*-setup.exe -Algorithm SHA256`
  - Linux: `sha256sum -c SHA256SUMS-linux.txt`
- [ ] Hay una carpeta de pruebas con archivos que no importan (copias, no originales).

## 1. Instalación

**Windows (instalador)**

- [ ] Doble clic en `...-setup.exe`. Si no está firmado, SmartScreen avisa: "Más información" > "Ejecutar de todas formas".
- [ ] El instalador está en español y muestra la licencia.
- [ ] Instala sin pedir permisos de administrador.
- [ ] Aparece en el menú Inicio; el acceso directo del escritorio solo si se marcó.
- [ ] El icono es el del programa (no el de Python) en el menú, la ventana y la barra de tareas.
- [ ] Propiedades del `.exe` > Detalles: nombre, versión y descripción correctos.

**Windows (portable)**

- [ ] Descomprimir el `.zip` y abrir `AnalizadorDisco.exe` funciona sin instalar nada.

**Ubuntu (.deb)**

- [ ] `sudo apt install ./analizador-disco_*.deb` instala sin errores de dependencias.
- [ ] Aparece en el menú de aplicaciones con su icono.
- [ ] `analizador-disco --version` responde en una terminal.

**Ubuntu (AppImage)**

- [ ] `chmod +x AnalizadorDisco-*.AppImage` y doble clic lo abre. (En Ubuntu 24.04 puede hacer falta `sudo apt install libfuse2t64`.)

## 2. Primera ejecución

- [ ] No aparece ninguna ventana de consola negra (Windows).
- [ ] Se abre el asistente de bienvenida, con tres pasos.
- [ ] No se puede pulsar "Empezar" sin marcar la casilla del último paso.
- [ ] Cerrar el asistente con la X cierra el programa, y al abrirlo otra vez vuelve a salir.
- [ ] Tras aceptarlo, no vuelve a aparecer en el siguiente arranque.

## 3. Escaneo

- [ ] Inicio muestra una tarjeta por disco con su porcentaje y el color que le corresponde.
- [ ] Escanear la carpeta de pruebas termina y lleva a "Explorar espacio".
- [ ] Escanear la carpeta personal: la ventana responde mientras tanto (se puede cambiar de sección).
- [ ] "Cancelar" y la tecla Esc detienen un escaneo largo.
- [ ] Escanear `C:\` o `/` completo no cierra el programa aunque haya carpetas sin permiso; al final indica cuántos elementos se ignoraron.
- [ ] Una carpeta que no existe muestra un aviso claro.

## 4. Explorar espacio

- [ ] Mapa de bloques: se ven bloques de colores con su leyenda.
- [ ] Al pasar el ratón sale nombre, tamaño y porcentaje.
- [ ] Clic en una carpeta entra en ella; la ruta de arriba permite volver.
- [ ] Árbol de carpetas: se despliega y muestra tamaño y porcentaje.
- [ ] Tabla de archivos: ordena por tamaño, modificado y último acceso; filtra por tipo y tamaño mínimo.
- [ ] Clic derecho > "Abrir ubicación" abre el explorador de archivos en esa carpeta.
- [ ] Clic derecho > "Copiar ruta" copia la ruta al portapapeles.

## 5. Seguridad al mover y borrar

- [ ] En "Archivos basura", el contador suma al marcar casillas.
- [ ] La ventana de confirmación muestra la lista exacta y aparece con **"Solo simular" marcado**.
- [ ] Con "Solo simular", no cambia nada en el disco.
- [ ] Desmarcándolo, los archivos de prueba aparecen en la **papelera** y se pueden restaurar.
- [ ] Con más de 1 GB seleccionado, pregunta una **segunda vez** y la respuesta predeterminada es "No".
- [ ] "Mover a otra carpeta": mueve, y si el nombre ya existe guarda como `nombre (1)`.
- [ ] No ofrece mover ni borrar `C:\Windows`, `Program Files`, `/usr`, `/etc`, ni las carpetas Documentos, Escritorio o Imágenes.
- [ ] Nada dentro de Documentos, Escritorio o Imágenes aparece en "Archivos basura" ni en la lista de duplicados sugeridos.
- [ ] Un archivo abierto en otro programa se omite y se avisa; el resto se procesa.
- [ ] Configuración > "Abrir el registro de acciones" muestra una línea por cada elemento movido o borrado.

## 6. Salud del disco y permisos

**En todos los sistemas**

- [ ] Sin smartmontools instalado, explica cómo instalarlo.
- [ ] Abrir la aplicación y entrar en "Salud del disco" **no** pide permisos ni contraseña.
- [ ] Los discos que no exigen permisos se muestran con su semáforo.
- [ ] Un disco que los exige muestra modelo, capacidad y tipo, un texto corto y el botón "Dar permiso y leer salud".
- [ ] En ningún sitio se pide cerrar el programa ni abrir PowerShell o una terminal.
- [ ] El resto del programa nunca pide permisos de administrador.

**Windows con cuenta de administrador**

- [ ] Pulsar el botón muestra el aviso de Control de cuentas de usuario (UAC), una sola vez.
- [ ] Aceptar: aparecen los datos de **todos** los discos.
- [ ] Cancelar ("No"): mensaje tranquilo, sin ventana de error, y el botón sigue disponible.
- [ ] Tras aceptar, "Prueba corta" vuelve a pedir permiso y la inicia.

**Windows con cuenta de usuario estándar** (la que usa la mayoría en equipos de empresa o familiares)

- [ ] Pulsar el botón pide el usuario y la contraseña de un administrador.
- [ ] Introducirlos: aparecen los datos de todos los discos.
- [ ] Cancelar, o contraseña incorrecta: mensaje tranquilo y el botón sigue disponible.
- [ ] No queda ningún archivo `analizador-disco-*.json` en la carpeta temporal del usuario (`%TEMP%`).

**Linux con agente de polkit** (GNOME, KDE, Cinnamon... con el `.deb` instalado)

- [ ] Pulsar el botón abre la ventana de contraseña, con el mensaje en español de Analizador de disco.
- [ ] Contraseña correcta: aparecen los datos de todos los discos.
- [ ] Una segunda lectura en los minutos siguientes no vuelve a pedir la contraseña.
- [ ] Cerrar la ventana: mensaje tranquilo y el botón sigue disponible.
- [ ] `ls -l /usr/lib/analizador-disco/ayudante` muestra propietario `root` y sin permiso de escritura para otros.

**Linux sin agente de polkit** (sesión mínima, o por SSH)

- [ ] Pulsar el botón (o `analizador-disco cli salud --elevar`) no se queda colgado: indica el comando `sudo` alternativo.
- [ ] `sudo analizador-disco cli salud` muestra todos los discos.

**Terminal**

- [ ] `salud` sin permisos indica que se puede añadir `--elevar`.
- [ ] `salud --elevar` pide los permisos y muestra todos los discos.

## 7. Otras secciones

- [ ] Duplicados: "Buscar duplicados" encuentra dos copias de prueba; el original no se puede marcar.
- [ ] Historial: tras dos escaneos de la misma carpeta, hay línea en la gráfica y comparación.
- [ ] Configuración: el tema claro y el oscuro se aplican al instante y se recuerdan al reabrir.
- [ ] "Acerca de" (F1): muestra nombre, versión, licencia, "Licencias de terceros" y el aviso de privacidad.

## 8. Privacidad

- [ ] Con la red desconectada, todo funciona igual.
- [ ] Con un monitor de red (Monitor de recursos en Windows; `ss -tp` o `nethogs` en Linux), el programa no abre ninguna conexión durante un uso normal.

## 9. Terminal y web con el mismo ejecutable

- [ ] `AnalizadorDisco --version` y `AnalizadorDisco cli resumen` responden (en PowerShell, añadiendo `| Out-Host`).
- [ ] `AnalizadorDisco web` abre `http://127.0.0.1:5000`, y desde otro equipo de la red esa dirección **no** es accesible.

## 10. Errores

- [ ] Elegir como destino de "Mover" una carpeta inexistente muestra un mensaje claro, sin jerga.
- [ ] La ventana de error tiene "Copiar detalle técnico" y lo copiado incluye la versión y el sistema.
- [ ] Desconectar un disco externo durante el escaneo no cierra el programa.

## 11. Desinstalación

- [ ] Windows: "Agregar o quitar programas" lo desinstala y desaparecen los accesos directos.
- [ ] Ubuntu: `sudo apt remove analizador-disco` lo quita del menú.
- [ ] El historial y el registro siguen en la carpeta de datos (es intencionado) y se pueden borrar a mano:
  - Windows: `%LOCALAPPDATA%\analizador-disco`
  - Linux: `~/.local/share/analizador-disco`
