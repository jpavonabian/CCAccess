# CCAccess

Aplicación de escritorio para gestionar **contactos** y **calendario** de cualquier servidor **CardDAV/CalDAV** (Nextcloud, Radicale, Baïkal, mailbox.org…). Pensada desde el principio para **lectores de pantalla** usando las pautas **WCAG 2.2** para garantizar accesibilidad.

La idea vino porque uso [DAVx⁵](https://www.davx5.com/) en Android y necesitaba algo accesible que funcionara en el ordenador y que se sincronizara con el servidor.

> Estado: **versión 0.1**, primera versión pública. Se ha probado en Windows 11 con mailbox.org (contactos) y con un servidor Radicale local (contactos y calendario, con crear, editar y borrar). La interfaz se ha revisado manualmente con **NVDA** y no se encontraron problemas. JAWS, Narrator, Orca y VoiceOver no se han probado todavía pero dice la teoría que deberían funcionar.

## Funciones

- Cuenta con URL, usuario y contraseña. La contraseña se guarda en el llavero del sistema.
- **Contactos:** lista con búsqueda, detalles, crear, editar y eliminar. Al editar se conservan los campos que la app no muestra (cumpleaños, foto, campos personalizados) y el tipo de cada teléfono.
- **Calendario:** agenda agrupada por día (7, 30 o 90 días), con recurrencias expandidas. Crear, editar y eliminar eventos, de hora o de todo el día.
- Detección de cambios en el servidor: si alguien modificó el elemento mientras lo editabas, la app no sobrescribe y te avisa.
- Opción **Archivo > Borrar datos guardados** para quitar del equipo la URL, el usuario y la contraseña.
- Sin caché en disco: contactos y eventos se descargan del servidor y viven solo en memoria.

## Accesibilidad

- Interfaz nativa con Qt (widgets estándar).
- Todo se maneja con teclado. Cada campo tiene su etiqueta asociada y atajos con mnemónicos.
- Los estados y errores se muestran en cuadros de diálogo y se anuncian al lector de pantalla.
- Fechas como `dd/mm/aaaa` y horas como `hh:mm` en campos de texto, porque son más predecibles con lector de pantalla que los selectores de fecha.
- La agenda es un árbol por días, no una cuadrícula dibujada.


### Atajos

| Atajo | Acción |
| --- | --- |
| `Ctrl+1` / `Ctrl+2` | Pestaña de contactos / calendario |
| `Ctrl+N` | Nuevo contacto o evento |
| `Ctrl+E` o `Enter` | Editar el elemento seleccionado |
| `Supr` | Eliminar (pide confirmación) |
| `Ctrl+F` | Ir a la búsqueda de contactos |
| `Ctrl+L` | Ir a la lista de contactos |
| `F5` | Actualizar |
| `Ctrl+Shift+A` | Configurar la cuenta |

Si encuentras algo que no funciona bien con tu lector de pantalla, abre una [incidencia](../../issues) indicando lector, versión y qué anuncia.

## Instalación (Windows)

1. Descarga `CCAccess-0.1.0-windows.zip` desde [Releases](../../releases).
2. Descomprímelo y ejecuta `CCAccess.exe`.

El ejecutable no está firmado, así que Windows SmartScreen puede mostrar un aviso la primera vez.

## Configurar tu cuenta

Abre **Archivo > Cuenta** (`Ctrl+Shift+A`) e introduce:

- **URL:** la dirección DAV de tu servidor. Para contactos, mailbox.org usa `https://dav.mailbox.org/carddav/`. La de calendario se deduce cambiando `/carddav/` por `/caldav/`. En Nextcloud suele ser `https://tu-servidor/remote.php/dav`.
- **Usuario y contraseña.** Si tu servidor usa verificación en dos pasos, crea una contraseña de aplicación.

## Dónde se guardan los datos

| Dato | Windows | Linux | macOS |
| --- | --- | --- | --- |
| URL y usuario | Registro: `HKCU\Software\CCAccess` | `~/.config/CCAccess/` | `~/Library/Preferences/` |
| Contraseña | Administrador de credenciales | Servicio de secretos del escritorio | Llavero |

## Ejecutar desde el código fuente

Requiere Python 3.11 o superior.

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run_ccaccess.py
```

En Linux y macOS usa `source .venv/bin/activate`. Esas plataformas no se han probado todavía.

Tests:

```powershell
pytest
```

## Crear el ejecutable

```powershell
pip install pyinstaller
.\build.ps1
```

Genera `dist\CCAccess\CCAccess.exe`.

## Limitaciones conocidas (0.1)

- Solo se ha probado el ejecutable en Windows y con NVDA. Sin probar con JAWS, Narrator, Orca ni VoiceOver.
- Los eventos que se repiten solo permiten cambiar título, lugar y descripción (afecta a toda la serie). No se editan fechas, excepciones ni alarmas.
- No hay tareas, alarmas ni invitados.
- Sin caché: hace falta conexión para ver cualquier dato.

## Licencia

[MIT](LICENSE)
