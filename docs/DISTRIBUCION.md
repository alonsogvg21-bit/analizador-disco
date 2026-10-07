# Compilar, publicar y firmar

Guía para quien mantiene el proyecto. Los usuarios finales no necesitan nada
de esto: les basta con el instalador (ver el README).

## Compilar en tu equipo

```
pip install -r requirements-empaquetado.txt
python build.py                # carpeta con el ejecutable + paquete portable + SHA-256
python build.py --instalador   # además, el instalador de este sistema
```

Se compila para el sistema en el que se ejecuta. Los archivos quedan en
`dist/entregables/`.

| Sistema | Archivo | Hace falta |
|---|---|---|
| Windows | `AnalizadorDisco-X.Y.Z-windows-x64-portable.zip` | nada más |
| Windows | `AnalizadorDisco-X.Y.Z-windows-x64-setup.exe` | [Inno Setup 6](https://jrsoftware.org/isdl.php) |
| Linux | `AnalizadorDisco-X.Y.Z-linux-x86_64.tar.gz` | nada más |
| Linux | `AnalizadorDisco-X.Y.Z-x86_64.AppImage` | [appimagetool](https://github.com/AppImage/appimagetool/releases) |
| Linux | `analizador-disco_X.Y.Z_amd64.deb` | `dpkg-deb` (Debian, Ubuntu) |
| Ambos | `SHA256SUMS-windows.txt` / `SHA256SUMS-linux.txt` | nada más |

Piezas:

- `analizador-disco.spec`: la receta de PyInstaller (carpeta, sin consola, recursos incluidos).
- `build.py`: ejecuta PyInstaller, comprueba que el paquete está completo, crea instaladores y sumas.
- `instalador/windows/analizador-disco.iss`: instalador de Inno Setup, en español.
- `instalador/linux/analizador-disco.desktop`: entrada del menú de aplicaciones.
- `utils/rutas.py`: encuentra los recursos tanto en desarrollo como dentro del paquete (`sys._MEIPASS`).
- `utils/info.py`: nombre y versión; es el único sitio donde se cambian.

Compila en Linux con una distribución antigua (Ubuntu 22.04): lo compilado ahí
funciona en sistemas más nuevos, pero no al revés.

## Publicar una versión

1. Cambia `VERSION` en `utils/info.py`.
2. Repasa `docs/PRUEBAS_MANUALES.md` con los instaladores de la rama.
3. Crea y sube la etiqueta:

   ```
   git tag v1.2.3
   git push origin v1.2.3
   ```

El flujo `.github/workflows/compilar.yml` compila en Windows y Linux, ejecuta
las pruebas, crea los instaladores y las sumas, y publica la versión en GitHub
con todos los archivos. También se puede lanzar a mano desde la pestaña
**Actions** (botón *Run workflow*): en ese caso los archivos quedan como
artefactos de la ejecución, sin publicar versión.

## Comprobar una descarga

Las sumas SHA-256 permiten saber que el archivo no se ha dañado ni alterado.

```powershell
Get-FileHash .\AnalizadorDisco-1.0.0-windows-x64-setup.exe -Algorithm SHA256
```

```bash
sha256sum -c SHA256SUMS-linux.txt
```

El resultado debe coincidir con la línea correspondiente del archivo de sumas.

## Firma de código (opcional)

Sin firma el programa funciona igual, pero Windows muestra el aviso de
SmartScreen ("editor desconocido") al instalar. La firma elimina ese aviso y
demuestra quién publicó el archivo. El flujo ya trae los pasos; están
inactivos hasta que existan los secretos.

### Windows

1. Consigue un certificado de firma de código (*code signing*) de una entidad
   reconocida. Es de pago. Los certificados "OV" van ganando reputación en
   SmartScreen con el tiempo; los "EV" la tienen desde el principio, pero
   suelen ir en un dispositivo físico y no se pueden usar con este método.
2. Expórtalo a un archivo `.pfx` con contraseña y conviértelo a texto:

   ```powershell
   [Convert]::ToBase64String([IO.File]::ReadAllBytes("certificado.pfx")) | Set-Clipboard
   ```

3. En GitHub: **Settings > Secrets and variables > Actions > New repository secret**. Crea dos:

   | Secreto | Contenido |
   |---|---|
   | `WINDOWS_CERT_PFX_BASE64` | el texto copiado en el paso 2 |
   | `WINDOWS_CERT_PASSWORD` | la contraseña del `.pfx` |

Con eso, la siguiente compilación firma `AnalizadorDisco.exe` y el instalador
con `signtool`, con sello de tiempo. Para firmar en tu equipo, define
`FIRMA_PFX` (ruta del `.pfx`) y `FIRMA_CLAVE` antes de ejecutar `build.py`.

### Linux

Las AppImage y los `.deb` sueltos no se firman como en Windows. Lo habitual es
firmar el archivo de sumas con GPG:

1. Crea una clave (`gpg --full-generate-key`) y publica la parte pública.
2. Exporta la privada: `gpg --armor --export-secret-keys TU_ID`.
3. Crea los secretos:

   | Secreto | Contenido |
   |---|---|
   | `GPG_PRIVATE_KEY` | la clave privada exportada |
   | `GPG_PASSPHRASE` | su contraseña |

El flujo generará `SHA256SUMS-linux.txt.asc`. Quien descargue lo comprueba con
`gpg --verify SHA256SUMS-linux.txt.asc SHA256SUMS-linux.txt`.

### Precauciones

- Nunca guardes el certificado ni las claves en el repositorio.
- Los secretos no están disponibles en *pull requests* de otros repositorios,
  así que ahí la firma simplemente se omite.
- Si un certificado se filtra, revócalo con la entidad emisora y borra el secreto.

## El ayudante de salud y los permisos

Leer SMART exige administrador en algunos discos. La aplicación nunca corre
con privilegios: cuando el usuario pulsa "Dar permiso y leer salud" se lanza
solo el ayudante (`--helper`), definido en `core/ayudante.py`, y todo pasa por
`core/privilegios.py`.

- **Windows**: `ShellExecuteExW` con el verbo `runas`. El resultado se lee de
  un archivo temporal de nombre aleatorio que crea la aplicación; el ayudante
  solo puede rellenar ese archivo (debe existir, estar vacío y llamarse como
  los que crea la aplicación) y se borra al terminar.
- **Linux**: `pkexec` y la política
  `instalador/linux/io.github.alonsogvg21bit.analizador-disco.policy`
  (`auth_admin_keep`, mensaje en español).

### Por qué el ayudante debe estar en una carpeta de root (Linux)

El paquete `.deb` instala el programa en `/usr/lib/analizador-disco/programa/`
y el lanzador del ayudante en `/usr/lib/analizador-disco/ayudante`. Esa
carpeta pertenece a root y un usuario normal no puede escribir en ella.

Es imprescindible: polkit ejecuta ese archivo como administrador. Si estuviera
en una carpeta del usuario (su carpeta personal, `/tmp`...), cualquier
programa que corra con sus permisos podría sustituirlo y conseguir que su
propio código se ejecutara como root la próxima vez que se concedieran los
permisos. Por eso la política de polkit apunta a esa ruta exacta, y el
lanzador añade siempre `--helper`, de modo que con privilegios solo se puede
entrar en el modo ayudante.

Con la AppImage o el `.tar.gz`, que viven en carpetas del usuario, no hay
política instalada: `pkexec` muestra su aviso genérico y pide la contraseña
cada vez. Funciona, pero para uso habitual se recomienda el `.deb`.

### Si cambias el ayudante

- No añadas acciones sin necesidad, ni ninguna que reciba rutas o comandos.
- No uses `shell=True`; llama a smartctl con lista de argumentos y ruta absoluta.
- La validación del disco usa `fullmatch`, no `match`: con `$` se colaría un
  nombre terminado en salto de línea.
- `tests/test_privilegios.py` comprueba todo lo anterior.

## Licencias al distribuir

- El paquete incluye `LICENSE` y `NOTICE`, visibles desde "Acerca de".
- Qt (PySide6) se distribuye bajo LGPL: va como bibliotecas separadas, sin
  modificar, dentro de `_internal/PySide6`. No las fusiones en un único
  archivo ni las modifiques sin revisar las obligaciones de la LGPL.
- **smartmontools no se incluye** (es GPL). El usuario lo instala aparte si
  quiere la sección de salud. Si algún día se quisiera incluir, habría que
  acompañarlo de su licencia y de la oferta de su código fuente.
- Si añades una dependencia, añádela también a `NOTICE`.
