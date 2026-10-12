# Plan de migración a GTK4

Fecha: 2026-09-18. Base:
[`ad68cc378b7a187706bc2648c48b44d16fb80819`](https://gitlab.gnome.org/GNOME/dia/-/tree/ad68cc378b7a187706bc2648c48b44d16fb80819).
Este documento es una propuesta del fork experimental `jcrtexidor/dia` y no
una migración implementada. La [auditoría](source-audit.md) contiene la evidencia
de arquitectura. No se enviarán estos cambios generados con IA a GNOME/dia;
su [política](../../README.md#use-of-generative-ai) también alcanza documentación.

La estrategia conserva el modelo de objetos, `.dia`, Cairo y los filtros;
prepara fronteras en GTK3, introduce una UI GTK4 experimental y sólo cambia el
editor predeterminado después de demostrar paridad. La API/MCP puede avanzar
antes con el backend GTK3 aislado. Una reescritura completa en Python aumenta
el alcance sin resolver por sí sola geometría, persistencia, ABI ni renderizado.

## Dependencias y decisiones

La guía oficial recomienda partir de GTK 3.24 y resolver las APIs retiradas.
GTK4 cambia eventos, contenedores, menús, ciclo de vida y portapapeles, de modo
que cambiar `dependency('gtk+-3.0')` por `dependency('gtk4')` no basta.
Dia ya exige GTK >=3.24, pero declara `GDK_VERSION_MIN_REQUIRED=GDK_VERSION_3_8`
y tiene comentado `GTK_DISABLE_DEPRECATED` en
[meson.build](../../meson.build). La primera fase registrará esas advertencias
antes de endurecerlas. [Guía oficial GTK3→GTK4](https://docs.gtk.org/gtk4/migrating-3to4.html).

Se propone GTK >=4.10 como mínimo inicial para el prototipo, sujeto a comprobar
la versión disponible en el Ubuntu 26 concreto usado para validación. Esa base
permite usar `GtkFileDialog`, introducido en 4.10. La documentación online
consultada también muestra APIs posteriores: cada símbolo nuevo debe contrastarse
con la versión mínima y no incorporarse por aparecer en la documentación actual.
No se cambia el mínimo de compilación en esta entrega.
[GtkFileDialog](https://docs.gtk.org/gtk4/class.FileDialog.html).

GTK3 y GTK4 tendrán builds y procesos separados; ningún proceso cargará ambas
versiones. Se mantendrán distintos prefijos y directorios de plug-ins durante
la transición. Para el fork experimental, las preferencias y pruebas deben usar
un perfil aislado para no alterar la instalación cotidiana.

## Riesgos y destino de cada subsistema

| Área y fuente de Dia | Trabajo propuesto | Riesgo que debe demostrar la prueba |
| --- | --- | --- |
| `app/dia-canvas.c`: `dia_canvas_draw`, `dia_canvas_configure_event`; `lib/renderer/diacairo-interactive.c` | Mantener Cairo mediante `GtkDrawingArea` con función de dibujo y resize. Separar preparación del frame, invalidación y pintura. Evaluar `GtkSnapshot` sólo si las medidas justifican otro renderer. | Regiones desactualizadas, escalado, clipping, diferencias de uniones/flechas y latencia al arrastrar. |
| `app/disp_callbacks.c`: `ddisplay_canvas_events`; `app/tool.h`; herramientas en `app/*_tool.c` | Introducir una estructura de entrada propia con coordenadas, botón, modificadores y fase; adaptar controladores de teclado, movimiento, scroll y gestos. | Pérdida de doble clic, arrastre, eventos comprimidos, foco, IME o transformación de coordenadas. |
| `app/menus.c`: `add_plugin_actions`; `app/commands.c` | Separar comandos del callback `GtkAction`, modelar acciones con `GAction` y menús con `GMenuModel`/`GtkPopoverMenu`. Conservar un adaptador para rutas históricas de acciones Python. | Acciones duplicadas, sensibilidad incorrecta, atajos que operan sobre otro documento o plug-ins invisibles. |
| `app/main.c`, `app/app_procs.c`, `app/dia-application.c` | Introducir `GtkApplication`/`GApplication` y salida explícita para CLI; conservar las notificaciones de documentos existentes. | Apertura de múltiples archivos, activación remota, cierre con cambios y códigos de salida incorrectos. |
| `app/gtkwrapbox.*`, `app/gtkhwrapbox.*`, `app/interface.c`, editor de capas | Sustituir contenedores específicos y revisar composición/layout, referencias y callbacks de destrucción. | Widgets vivos después del cierre, objetos liberados aún referenciados y tamaños mínimos inservibles. |
| `app/commands.c`, `app/toolbox.c`, DnD en `app/dia-canvas.c` | Portapapeles con contenido tipado; `GtkDragSource`/`GtkDropTarget`. Sustituir el puntero transportado por un identificador validado del tipo/herramienta. | Pegar formatos incompatibles, lifetime del origen y fallos entre documentos/procesos. |
| `app/filedlg.c`, `app/exit_dialog.c`, `app/find-and-replace.c` | Flujo asíncrono con finalización/cancelación explícita, sin loops modales anidados. | Guardados después de cancelar, documento cerrado antes de completar o doble respuesta. |
| `lib/prop_sdarray_widget.c`, `app/diagram_tree_view.c`, `app/plugin-manager.c` | Mantener temporalmente APIs GTK4 compatibles donde facilite el primer port; migrar listas a `GListModel`, `GtkListView`/`GtkColumnView` y factorías. | Edición de propiedades, selección y orden conservados; filas recicladas con valores de otro objeto. |
| `objects/UML/*_dialog.c`, widgets de `lib/`, `.ui` y recursos | Inventariar editores de propiedades por familia y migrarlos con muestras reales. Convertir `.ui` con revisión manual; migrar por separado el XML de `GtkUIManager`. | Un tipo se dibuja pero no permite editarse, traducciones cortadas o propiedades perdidas al aceptar. |
| `plug-ins/python/gtkcons.py`, `python.c`, `pydia-*` | Conservar el módulo `dia` de CPython y sus operaciones probadas; portar consola y scripts GUI a Gtk 4.0 en el build GTK4. | Importación accidental de Gtk 3.0, callbacks con widgets antiguos y scripts de terceros incompatibles. |

GTK4 permite seguir dibujando con Cairo en `GtkDrawingArea`. Su callback de
dibujo debe limitarse a pintar; los cambios de widgets se preparan fuera de esa
etapa. Esto favorece una primera migración del lienzo sin reescribir las
primitivas de Dia. [Función de dibujo](https://docs.gtk.org/gtk4/method.DrawingArea.set_draw_func.html).
Los controladores se asocian a widgets y permiten administrar la propagación de
entrada; el adaptador propuesto conservará la semántica de las herramientas.
[GtkEventController](https://docs.gtk.org/gtk4/class.EventController.html).

`GtkPopoverMenu` construye menús a partir de modelos; el plan separa el nombre
de la acción de la ruta visual que hoy usan los plug-ins.
[GtkPopoverMenu](https://docs.gtk.org/gtk4/class.PopoverMenu.html).
Los atajos tendrán una tabla explícita y pruebas de ámbito por ventana.
[GtkShortcutController](https://docs.gtk.org/gtk4/class.ShortcutController.html).
El nuevo DnD deberá usar contenido con vida útil definida.
[GtkDragSource](https://docs.gtk.org/gtk4/class.DragSource.html).

`GtkTreeView` sigue existiendo en GTK4 y está deprecado desde 4.10: no debe
contabilizarse como un bloqueo de compilación equivalente a `GtkContainer`.
Su reemplazo es trabajo de modernización con criterios propios.
[GtkTreeView](https://docs.gtk.org/gtk4/class.TreeView.html).
La herramienta `gtk4-builder-tool simplify --3to4` da un punto de partida para
los `.ui`, no convierte todo el editor ni verifica comportamiento.
[gtk4-builder-tool](https://docs.gtk.org/gtk4/gtk4-builder-tool.html).

## Fases y criterios de salida

Los criterios son objetivos de aceptación, no resultados ya obtenidos. Cada
fase debe producir una revisión identificable, comandos reproducibles y
artefactos de prueba. No se asignan plazos sin una compilación basal y una
prueba del lienzo.

| Fase | Entrega | Criterio medible para avanzar |
| --- | --- | --- |
| 0. Baseline GTK3 | Build aislado de la base; inventario de dependencias, filtros y plug-ins; fixtures y métricas | Compilación terminada; resultado individual de todos los tests registrados; lista explícita de fallos basales; guardar/reabrir y exportar los fixtures definidos abajo. Registrar versión exacta de Ubuntu 26, arquitectura, compilador, Python, GTK y backend gráfico. |
| 1. API y MVP | Contrato tipado de documentos/objetos/conexiones y backend Dia por proceso; transporte MCP separado | Crear dos figuras y un conector, guardar `.dia`, recargar y verificar pertenencia/índices de conexión, exportar SVG y PNG válidos. Tipo, ID o punto inválidos, excepción Python y error de escritura no confirman cambios ni dejan un archivo final parcial. |
| 2. Preparación en GTK3 | Comandos independientes de `GtkAction`; entrada sin `GdkEvent*` en el contrato de herramientas; callbacks asíncronos donde corresponda | Suite basal sin regresiones; pruebas de comandos ejecutables sin construir menús; todas las herramientas reciben el contrato propio; inventario reproducible de deprecaciones pendientes por módulo. |
| 3. Frontera modelo/UI | Separación incremental de editores de propiedades y servicios GUI respecto a documento/renderizado | La API pública de automatización no contiene `GtkWidget`, `GdkEvent` ni punteros serializados. Muestras iguales a través de CLI/API. Documentar dependencias GTK restantes; sólo declarar núcleo sin GTK cuando exista target que compile y ejecute sin enlazarla. |
| 4. Lienzo GTK4 experimental | Build GTK4 separado con apertura, dibujo y herramientas esenciales; backend CLI conservado | Cargar los fixtures; seleccionar, mover, crear y conectar; texto con IME, zoom y paneo; guardar/reabrir sin pérdida de conexiones. Cero errores críticos nuevos de GTK en esos recorridos. |
| 5. Paridad del editor | Menús, atajos, propiedades, capas, portapapeles, DnD, diálogos, impresión y scripts GUI | Matriz funcional completa; cada diferencia frente a GTK3 aceptada explícitamente o corregida. Exportadores activos y familias de objetos documentados. Cancelación/cierre sin corrupción y navegación por teclado de las tareas principales. |
| 6. Adopción | Empaquetado de fork, revisión de ABI y documentación de compatibilidad | Suite automatizada y revisión visual aprobadas; ensayo de retorno a GTK3; sin regresiones funcionales abiertas de severidad bloqueante. Sólo entonces se cambia el ejecutable predeterminado. |

La fase 3 puede avanzar por módulos mientras se experimenta con el lienzo; no
se exige una extracción total de `libdia` para iniciar el prototipo. Su criterio
impide presentar el backend GTK3 por proceso como una biblioteca independiente.

## Matriz de validación

Los fixtures iniciales deben incluir `samples/render-test.dia`, un documento
con dos cajas y un conector, un ejemplo UML con propiedades compuestas, uno de
flujo con conectores ortogonales y otro con texto UTF-8, capas, grupos e imagen.
Añadir al menos una muestra por familia de objetos que el fork declare
compatible. Capturar los mismos ejemplos antes y después de cada fase.

| Dimensión | Comprobación requerida |
| --- | --- |
| Construcción | GTK3 y GTK4 en directorios/prefijos separados; advertencias nuevas atribuidas; no mezclar módulos compilados para otro ABI. |
| Tests existentes | Ejecutar `meson test -C <build> --print-errorlogs`; distinguir tests registrados de `test-export`, que está desactivado en la base. Xvfb puede servir a tests GTK3 que necesitan display; no sustituye la prueba de Wayland. |
| Semántica `.dia` | Abrir–guardar–abrir; comparar tipos, propiedades, capas, geometría con tolerancia numérica fijada e identidades de extremos. No exigir igualdad de bytes del XML/gzip ni de IDs regenerados. |
| Exportación | SVG parseable, PNG decodificable con dimensiones esperadas y `.dia` recargable. Comprobar archivo nuevo, retorno y errores. Probar directorio sin escritura y filtro inexistente. |
| Imagen | Comparar rasterizaciones con fuentes y escala fijadas; establecer tolerancia a partir del baseline y revisar cada diferencia que la exceda. Revisar texto, flechas, trazos, clipping y transparencia. |
| Entrada | Ratón, touchpad, teclado, doble clic, selección múltiple, arrastre de handles, scroll suave, zoom centrado e IME. Registrar coordenadas de documento esperadas en pruebas del adaptador. |
| Sesión | Abrir dos documentos; editar/cerrar/cancelar/reabrir; guardar como; perder foco durante un drag; cancelar exportación y diálogos sin aplicar acciones posteriores. |
| Escritorio | Sesión Wayland real en el Ubuntu 26 verificado, escalas 100% y 200%; X11 sólo si se declara soportado y existe en el entorno. Probar atajos y accesibilidad por teclado, no sólo capturas de pantalla. |
| Memoria | ASan/UBSan donde el entorno lo permita; repetir 100 ciclos de abrir–editar–cerrar en el perfil de prueba y comprobar errores de vida útil. Registrar la tendencia de memoria, sin confundir caché estable con fuga. |
| Rendimiento | Dataset determinista de 100, 1.000 y 10.000 objetos; cinco repeticiones de carga/exportación y muestra de latencia de drag. Comparar mediana, p95 y RSS contra GTK3 en el mismo equipo. Objetivo inicial: no empeorar más de 20% sin explicación y aceptación. |
| Automatización | Pruebas de contrato idénticas para cada backend; respuestas de error estables; exportación fallida no cambia el documento lógico; stdout de MCP reservado al protocolo y diagnósticos a stderr. |

Los porcentajes, tamaños y repeticiones son umbrales propuestos del fork; no
proceden de GTK ni describen mediciones ya realizadas. Las plataformas Windows
y macOS necesitarán sus propios builds y pruebas antes de anunciar soporte;
el baseline Linux no lo demuestra.

## Python, hilos y evolución del backend

La API/MCP externa conserva IDs y snapshots; CPython embebido materializa cada
trabajo en un proceso Dia separado. La reconstrucción completa limita la
primera versión a documentos administrados por ese servicio; editar documentos
arbitrarios o adjuntarse al editor requerirá otro contrato y pruebas de
preservación de propiedades desconocidas. No añadir `eval`, comandos de shell
ni imports suministrados por el cliente para ampliar operaciones.

Si más adelante se introduce un backend persistente dentro de la GUI, deberá
serializar mutaciones en el hilo principal, conservar propiedad y vida útil de
objetos y adaptar las operaciones a la pila de undo. GTK documenta que la
mayoría de sus objetos sólo pueden usarse desde el hilo principal; añadir el GIL
de Python no resuelve esa restricción.
[Modelo de hilos GTK](https://docs.gtk.org/gtk4/section-threading.html).

Las operaciones y el protocolo se versionan aparte del toolkit. Primero se
mantiene compatibilidad con scripts PyDia que sólo usan el modelo; los scripts
GUI declaran GTK3 o GTK4 y se ejecutan sólo en su build correspondiente. Los
plug-ins C se recompilan y su ABI se revisa al cambiar callbacks o estructuras
de `lib/object.h` y `lib/plug-ins.h`.

## Compatibilidad y retorno

1. Conservar el build GTK3 validado y el último conjunto de artefactos basales
   durante todas las fases. Los builds experimentales usan perfiles y directorios
   de plug-ins separados.
2. No introducir cambios al formato `.dia` como parte incidental del port.
   Verificar también que GTK3 abre los archivos guardados por GTK4. Si una
   función exige nuevo formato, versionarla y tratarla como proyecto aparte.
3. Confirmar salidas mediante temporal y reemplazo sólo tras validación. Para
   pruebas de ida y vuelta, guardar copias; conservar los originales del corpus.
4. Ante corrupción, desconexión de extremos, errores de vida útil o regresión
   visual sin explicar, detener la promoción de la fase. Volver al ejecutable
   GTK3 y a la revisión anterior del adaptador conservando archivos y evidencias
   del fallo; no revertir trabajo ajeno ni borrar documentos.
5. Ensayar el retorno: abrir con GTK3 los archivos producidos por el prototipo,
   recuperar el perfil anterior y repetir crear–conectar–exportar usando el
   backend anterior con el mismo contrato. Registrar cualquier incompatibilidad.

La aprobación de GTK4 depende de esas evidencias. Compilar el prototipo o
conseguir una exportación correcta no completa la migración del editor.
