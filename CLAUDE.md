# CCAccess

App de escritorio (PySide6/Qt) para contactos (CardDAV) y calendario (CalDAV), pensada para lectores de pantalla (NVDA) y WCAG 2.2. Repo: `jpavonabian/CCAccess`. Idioma de la interfaz, README, commits y respuestas al usuario: **español**.

## Antes de mirar archivos

1. **Consulta primero el grafo** (`graphify-out/`, no se versiona):
   - Lee `graphify-out/GRAPH_REPORT.md` para la arquitectura y los nodos clave.
   - Para preguntas concretas usa `graphify query "<pregunta>"`, `graphify path "A" "B"` o `graphify explain "X"`.
   - Solo abre archivos cuando el grafo no baste o vayas a editarlos, y lee únicamente lo necesario.
2. Si falta `graphify-out/` o está desfasado tras cambios grandes, regenera con `/graphify . --update`.
3. Nada de barridos amplios con Grep/Glob "por si acaso" si el grafo ya responde.

## Estructura

- `ccaccess/carddav.py`, `caldav_client.py`: clientes DAV sin Qt.
- `ccaccess/vcard_form.py`: conversión formulario ↔ vCard (editor completo de contactos).
- `ccaccess/updater.py`: autoactualización desde Releases de GitHub (sin Qt).
- `ccaccess/ui/`: ventana principal, pestañas, diálogos. `dialogs.py` tiene los componentes accesibles compartidos.
- `tests/`: pytest. Sin Qt salvo comprobaciones puntuales.

## Accesibilidad (innegociable)

- Cada campo con `QLabel` + `setBuddy` y mnemónico (`&`). Orden de tabulación lógico.
- Botones: usar `EnterButton` (de `ui/dialogs.py`), no `QPushButton`: el estándar solo responde a Espacio.
- Cuadros de solo lectura: `make_readonly_navigable(box)`, **nunca** `setReadOnly(True)` a secas (en Qt 6.12 deja sin cursor ni selección por teclado y NVDA solo lee la primera línea).
- Estados y errores: `self.say(...)` (barra de estado + `announce`) o diálogo. No añadir diálogos para avisos informativos sin necesidad (p. ej. libreta vacía va a la barra de estado).
- Fechas `dd/mm/aaaa` y horas `hh:mm` en campos de texto, no selectores.
- Árbol por días para la agenda, no cuadrículas dibujadas.
- Tras cambiar UI, verificar con simulación de teclas (`QTest`) y pedir al usuario que pruebe con NVDA: el entorno no tiene lector de pantalla.

## Hilos

- Nunca tocar la interfaz desde un hilo de trabajo. Todo trabajo de red pasa por `MainWindow._run` / `_run_silent`, que ejecuta los callbacks **en el hilo principal**. No conectar señales del `Worker` directamente a lambdas o funciones sueltas (corren en el hilo del worker: bloquea la UI y no deja crear diálogos).

## Datos y seguridad

- Contraseña solo en el llavero del sistema (`keyring`). Sin caché en disco de contactos ni eventos.
- Al guardar un vCard conservar lo que la app no edita (foto, `X-…`, parámetros `TYPE`). Hay tests; no romperlos.
- Cambios al servidor con `If-Match`/ETag: no sobrescribir si cambió.
- El actualizador verifica SHA-256 y rechaza rutas peligrosas en el ZIP; no relajar eso.
- vobject: `NICKNAME`, `TITLE`, `ROLE`, `NOTE` llevan texto; `ORG` y `CATEGORIES` listas. Una lista donde va texto rompe `serialize()`.

## Desarrollo y pruebas

- Entorno: `.venv`. Tests: `.venv/Scripts/python.exe -m pytest -q` (deben pasar todos antes de cualquier commit).
- Probar Qt sin pantalla con `QT_QPA_PLATFORM=offscreen`. **Un diálogo modal cuelga el script**: parchear `QMessageBox.information/warning` o evitar la acción que lo abre. Poner siempre `timeout`.
- La consola de Windows es cp1252: no imprimir flechas ni caracteres exóticos en scripts de prueba.
- Para escribir archivos con tildes o comillas complicadas usar las herramientas Write/Edit, no heredocs con escapes. Comprobar que un reemplazo programático no duplica código (pasó una vez en `main_window.py`).
- Los archivos del repo pueden tener finales de línea CRLF; los scripts de edición deben respetarlos.

## Releases

- Versión en `ccaccess/__init__.py`. Etiqueta `vX.Y.Z` debe coincidir con `__version__` o el workflow falla.
- Flujo: subir versión → tests → commit → `git tag vX.Y.Z` → `git push origin main vX.Y.Z`. GitHub Actions (`.github/workflows/release.yml`) construye con PyInstaller, hace `--selftest`, y publica ZIP + `SHA256SUMS.txt`.
- Si la etiqueta no dispara el workflow: `gh workflow run release.yml -f tag=vX.Y.Z`.
- **No commitear, etiquetar ni publicar sin que el usuario lo pida en ese turno.** Nunca borrar ni mover etiquetas remotas ni forzar push.
- El `.exe` empaquetado incluye `README.md` (menú Ayuda > Ver manual): mantener el README al día con cada cambio visible.

## Estilo

- Cambios mínimos y centrados; sin refactors no pedidos.
- Comentarios solo cuando explican un porqué que no es obvio (como los de accesibilidad o hilos).
