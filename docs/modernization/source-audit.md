# Auditoría de arquitectura y Python

Fecha: 2026-09-18. Base upstream: GNOME/dia, revisión
[`ad68cc378b7a187706bc2648c48b44d16fb80819`](https://gitlab.gnome.org/GNOME/dia/-/tree/ad68cc378b7a187706bc2648c48b44d16fb80819).
Los hallazgos de código describen esa base, antes de los cambios experimentales
del fork. Las rutas relativas permiten inspeccionar la implementación local;
los nombres de símbolos sirven para localizarla aunque cambien las líneas.

Este documento pertenece al fork experimental `jcrtexidor/dia`. El
[README upstream](../../README.md#use-of-generative-ai) excluye contribuciones
generadas con IA, también documentación; [HACKING.md](../../HACKING.md) remite a
esa política. Estos cambios no se enviarán a GNOME/dia como contribución, issue
o solicitud de soporte. Se conservan las licencias y atribuciones existentes.

## Conclusión técnica

Dia ya dispone de un modelo de objetos extensible, serialización nativa,
renderizadores y un módulo Python embebido. Esa base permite construir el MVP
de automatización sin reescribir el editor en Python ni esperar a GTK4.
Sin embargo, `libdia` todavía depende de GTK3 y PyDia expone punteros y
operaciones de bajo nivel: no constituye por sí solo una API remota segura,
transaccional o independiente del proceso.

Esta auditoría es estática. No acredita una compilación, ejecución en Ubuntu
26, funcionamiento de exportadores ni equivalencia visual. Esos resultados
deben acompañar a la implementación y sus pruebas. La migración GTK4 sigue
siendo el [plan separado](gtk4-migration.md).

## Mapa de componentes

| Componente | Evidencia en la base | Implicación |
| --- | --- | --- |
| Construcción | [meson.build](../../meson.build): `project`, `libgtk_dep`, `libxml_dep`; [BUILDING.md](../../BUILDING.md) | Proyecto 0.98.0, C GNU17 y C++20; Meson >=1.1.0, GTK >=3.24, GLib/GIO >=2.80, libxml2 >=2.14.0 y Graphene >=1.10. Registrar versiones realmente resueltas al probar. |
| Biblioteca | [lib/meson.build](../../lib/meson.build): `libdia_sources`, `libdia_deps` | Modelo, propiedades, widgets y renderizadores se compilan juntos; `libgtk_dep` forma parte de la dependencia pública. |
| Objetos | [lib/object.h](../../lib/object.h): `DiaObject`, `DiaObjectType`, `ObjectOps`; [objects/standard](../../objects/standard) | Las factorías crean objetos y handles; las operaciones gestionan geometría, propiedades, carga y guardado. El header incluye GTK y callbacks de editores `GtkWidget *`. |
| Documento | [lib/diagramdata.h](../../lib/diagramdata.h): `DiagramData`, `data_update_extents`, `data_render`; [lib/layer.c](../../lib/layer.c) | Capas y objetos son reutilizables por importadores sin una ventana; el cálculo de extensión precede a la exportación. |
| Editor | [app/diagram.c](../../app/diagram.c), [app/display.c](../../app/display.c), [app/undo.c](../../app/undo.c) | Documento, displays, selección, actualizaciones visuales y undo tienen responsabilidades adicionales al modelo básico. |
| Persistencia | [app/load_save.c](../../app/load_save.c): `read_connections`, `write_connections` | `.dia` guarda referencias entre objetos e índices de conexión. Cambiar el orden de puntos rompe conexiones de archivos existentes. |
| Renderizado | [lib/diarenderer.h](../../lib/diarenderer.h), [lib/renderer/diacairo-renderer.c](../../lib/renderer/diacairo-renderer.c), [lib/diainteractiverenderer.h](../../lib/diainteractiverenderer.h) | La abstracción `DiaRenderer` y Cairo permiten mantener exportación y geometría mientras cambia la presentación GTK. |
| Extensiones | [lib/plug-ins.h](../../lib/plug-ins.h): `DIA_PLUGIN_API_VERSION`, `DIA_PLUGIN_CHECK_INIT`; [plug-ins/meson.build](../../plug-ins/meson.build) | API de plug-ins versión 21. Varios módulos enlazan GTK; cualquier cambio de estructuras públicas exige revisar ABI y reconstruirlos. |
| Arranque | [app/main.c](../../app/main.c): `main`; [app/app_procs.c](../../app/app_procs.c): `app_init`, `do_convert` | El editor usa `gtk_main`; el modo CLI intenta `gtk_init_check`. Sin ventanas no significa ausencia de GTK o de necesidades de display de todos los módulos. |
| Estado de aplicación | [app/dia-application.c](../../app/dia-application.c): `G_DEFINE_TYPE`, `dia_application_get_default` | `DiaApplication` hereda de `GObject`, no de `GtkApplication`, aunque ya usa `GListStore` para documentos. |

## PyDia: qué existe y qué no

[plug-ins/python/python.c](../../plug-ins/python/python.c), en
`dia_plugin_init`, registra `PyInit_dia` con `PyImport_AppendInittab` e inicia
CPython con `PyConfig`/`Py_InitializeFromConfig`. Es integración del intérprete
dentro del ejecutable, coherente con el modelo oficial de
[Python embebido](https://docs.python.org/3/extending/embedding.html).
`import dia` funciona en ese intérprete; no implica que exista un paquete
instalable para importar desde cualquier `python3` externo.

[plug-ins/python/meson.build](../../plug-ins/python/meson.build) solicita
`python3-embed >=3.8`, compila `python_plugin` y lo enlaza a `diaapp`
(`link_with: [diaapp]`). Aunque BUILDING describe Python como opcional, el
Meson inspeccionado entra incondicionalmente en `subdir('python')` y la llamada
a `dependency('python3-embed', ...)` no establece `required: false`.
El `if py3_dep.found()` posterior no convierte esa búsqueda en opcional.
No hay una opción Python en [meson_options.txt](../../meson_options.txt).

El módulo implementado en
[diamodule.c](../../plug-ins/python/diamodule.c) permite `new`, `load`,
`get_object_type`, enumerar tipos y registrar importadores, renderizadores de
exportación y acciones. Sus wrappers permiten, entre otras cosas:

| Necesidad | API existente | Obligación de la nueva capa |
| --- | --- | --- |
| Crear | `dia.get_object_type(nombre).create(x, y)` en `pydia-object.c` | Validar el tipo y añadir el objeto a una capa; crear no equivale a insertarlo en un documento. |
| Propiedades | `Object.properties` en `pydia-properties.c` y `pydia-property.c` | Exponer una lista acotada de propiedades y tipos comprobados, con unidades y límites explícitos. |
| Insertar | `Layer.add_object` en `pydia-layer.c` | Mantener pertenencia a documento, orden y vida útil. |
| Conectar | `Handle.connect` en `pydia-handle.c`; `Object.move_handle` | Validar handle/punto, establecer conexión y actualizar posición; comprobar ambos aspectos al recargar `.dia`. |
| Actualizar | `Diagram.update_connections`, `add_update_all`, `flush` en `pydia-diagram.c` | Son servicios del editor. Un importador recibe `DiagramData`, que no ofrece todas las operaciones de `Diagram`. |
| Guardar | `Diagram.save` en `pydia-diagram.c` | Comprobar el retorno real: devuelve entero de `diagram_save`, aunque su docstring diga `None`; descarta detalles del `DiaContext`. |
| Exportar | Registro `DiaExportFilter` en `lib/filter.h`; CLI `-e`/`-t` | Elegir filtro explícito, propagar errores y validar el artefacto. `register_export` registra un renderizador, no es una llamada genérica para exportar un documento. |

### Límites observados

1. **Concurrencia y carga.** `dia_plugin_init` rechaza un intérprete ya
   inicializado y advierte que la integración no está diseñada para concurrencia.
   `dia_py_plugin_can_unload` retorna `FALSE`. No asumir reinicialización,
   subintérpretes, hilos de trabajo de PyDia ni carga/descarga repetida segura.
2. **Vida útil.** `PyDiaObject_New` guarda `DiaObject *`; su destructor Python
   sólo libera el wrapper. `Object.destroy` libera el objeto C. Otros wrappers
   pueden seguir conteniendo punteros al mismo objeto. Los IDs externos deben
   resolverse en un registro propio, no serializar direcciones o wrappers.
3. **Undo.** `PyDiaObject_Move` y `PyDiaObject_MoveHandle` liberan el
   `DiaObjectChange` devuelto sin añadirlo a la pila de undo. No prometer undo
   del editor ni transacciones porque una llamada Python haya terminado.
4. **Conexiones.** `object_connect` en `lib/object.c` enlaza handle y punto;
   `read_connections` además mueve el handle al cargar. En la base,
   `PyDiaHandle_Connect(None)` accede a `connected_to->object` sin comprobar
   que exista conexión. Evitar esa ruta si ya está desconectado.
5. **Importación y errores.** `PyDia_import_data` toma la existencia del
   objeto de retorno Python (`!!res`) como éxito. Un `False` explícito también
   cuenta como éxito. La corrección necesita decidir cómo conservar importadores
   antiguos que retornan `None` y probar excepciones por separado.
6. **Exportación y errores.** `DiaExportFunc` retorna `gboolean`, pero
   `do_convert` ignora ese valor y retorna `TRUE`. `main` sale con 0 al finalizar
   `app_init` en modo no interactivo. Un proceso que termina con 0 no demuestra
   que el exportador escribió un archivo válido.
7. **Arranque de scripts.**
   [python-startup.py](../../plug-ins/python/python-startup.py) importa archivos
   `.py` del usuario (`~/.dia/python`) y luego del directorio del programa.
   Para una operación reproducible del backend hay que usar un arranque dedicado,
   controlar las rutas de módulos y evitar cargar extensiones personales.
8. **Interfaz Python.** [gtkcons.py](../../plug-ins/python/gtkcons.py) exige
   `gi.require_version('Gtk', '3.0')`. Esa consola y cualquier script que use
   widgets necesitan adaptación explícita; los scripts de geometría sin Gtk
   pueden conservar una interfaz compatible. No cargar GTK3 y GTK4 en el mismo
   proceso de Dia como solución de compatibilidad.

### Decisión para el MVP del fork

El diseño acordado mantiene una API Python externa con documentos lógicos e
IDs propios. Cada materialización usa un proceso Dia aislado y un
`python-startup.py` dedicado seleccionado con `DIA_PYTHON_PATH`; el arranque
registra un importador JSON `.diacmd`. Cuando Dia invoca el importador, éste
construye el snapshot mediante tipos nativos, `DiagramData.active_layer` y
handles. La exportación se dirige a un archivo temporal, se valida y sólo
entonces la API confirma su estado.

El transporte MCP por stdio pertenece al proceso Python externo y consume esa
API. No introduce un servidor de red ni ejecuta código Python recibido por el
protocolo. Tampoco controla una ventana de Dia ya abierta: el documento lógico
del servicio y el documento de una sesión GUI son estados distintos. Los IDs
son del contrato del servicio; no se deben confundir con índices de conexión o
IDs XML generados al guardar.

Este límite de proceso evita conservar punteros PyDia entre solicitudes y
permite abortar una materialización fallida sin modificar el documento lógico
anterior. Tiene un costo de arranque y reconstrucción completa que debe medirse.
GTK3 y, cuando haga falta, Xvfb siguen siendo dependencias del backend. El
aislamiento de proceso no constituye una sandbox para ejecutar código arbitrario.

## Superficie de migración GTK

Un escaneo textual de 592 archivos `.c`/`.h` bajo `app`, `lib`, `objects` y
`plug-ins` produjo lo siguiente. Las coincidencias incluyen declaraciones,
comentarios y usos repetidos; **no son número de llamadas ejecutadas ni una
estimación de jornadas**. También hay siete archivos `.ui` bajo `app`, `lib`
y `data`; gran parte de la UI se construye en C o mediante XML de menús.

| Familia buscada | Coincidencias / archivos | Concentración útil |
| --- | --- | --- |
| `GtkAction`, acciones toggle/radio, `GtkUIManager` y funciones correspondientes | 375 / 22 | `app/menus.c`, `app/commands.c`, `app/commands.h` |
| `GtkContainer`, `gtk_container_*` | 206 / 45 | `app/layer-editor/dia-layer-list.c`, `app/gtkwrapbox.c`, `objects/UML/class_operations_dialog.c` |
| `GdkWindow`, `gdk_window_*` | 29 / 10 | Editor de capas, `app/disp_callbacks.c` |
| Estructuras `GdkEventButton/Motion/Key/Scroll/Focus/Configure` | 98 / 25 | `app/disp_callbacks.c`, `app/interface.c`, `app/modify_tool.c` |
| `GtkClipboard`, `gtk_clipboard_*`, `gtk_drag_*` | 44 / 4 | `app/commands.c`, `app/toolbox.c`, `app/dia-canvas.c` |
| `gtk_dialog_run` | 8 / 5 | `app/filedlg.c`, `app/find-and-replace.c`, `app/exit_dialog.c`; incluye comentarios |
| `GtkTreeView*`, `GtkCellRenderer*` y funciones correspondientes | 292 / 25 | `lib/prop_sdarray_widget.c`, `app/diagram_tree_view.c`, `app/plugin-manager.c` |

El lienzo en [app/dia-canvas.c](../../app/dia-canvas.c) hereda de
`GtkDrawingArea`, implementa `configure_event`, `draw` y `event`, y conserva
regiones pendientes para el renderer interactivo. `ddisplay_canvas_events`
en [app/disp_callbacks.c](../../app/disp_callbacks.c) inspecciona y modifica
campos de eventos GDK. [app/tool.h](../../app/tool.h) lleva esas estructuras
GTK3 a todas las herramientas. Es una frontera prioritaria para desacoplar.

`GtkWrapBox` hereda de `GtkContainer`; los menús usan `GtkUIManager` y
`GtkAction`. El DnD de la paleta transmite un puntero `ToolButtonData *` dentro
del proceso. Estos detalles requieren cambios de diseño, no una sustitución
del nombre de la dependencia en Meson.

## Pruebas existentes y brechas

[tests/meson.build](../../tests/meson.build) registra `colour-selector`,
`colour`, `graphene`, `svg`, `boundinbox` (nombre escrito así), `objects` y
`xmllint`; `sizeof` es un helper. `test-export` se compila pero su registro
como prueba está comentado porque varios casos están rotos. Pasar el conjunto
registrado no acredita todos los formatos de exportación.

[tests/test-objects.c](../../tests/test-objects.c) ya comprueba creación,
movimiento, handles y consistencia de puntos de conexión. Debe conservarse y
complementarse con un circuito crear–conectar–guardar–recargar–exportar,
validación de fallos y revisión visual. Para la UI faltan evidencias específicas
de selección, IME, zoom, paneo, teclado, accesibilidad, DnD y diálogos cancelados.
Los criterios concretos están en el plan GTK4; ninguno se declara cumplido por
esta lectura de fuentes.
