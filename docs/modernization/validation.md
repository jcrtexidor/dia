# Validación de la entrega MVP

Fecha local: 2026-09-18, America/Montevideo (ejecución continuada el
2026-09-19 UTC). Base upstream:
`ad68cc378b7a187706bc2648c48b44d16fb80819`. Las pruebas nativas usan el
ejecutable compilado del fork y su módulo Python; no usan un paquete Dia
precompilado de otra versión.

## Entorno comprobado

| Componente | Valor observado |
| --- | --- |
| Host | Ubuntu 26.04.1 LTS, x86_64 |
| Contenedor | Ubuntu 26.04.1 LTS, amd64, imagen `ubuntu:26.04` fijada por digest |
| Docker | 29.8.1 |
| Dia | 0.98.0, GTK3, compilado desde este checkout |
| GCC | 15.2.0 |
| Meson | 1.10.1 |
| GTK | 3.24.52 |
| GLib | 2.88.0 |
| libxml2 | 2.15.2 |
| Python embebido / servidor | 3.14.4; intérprete embebido con prefix `/usr` |
| SDK MCP | 1.30.0, venv externo a PyDia |
| pytest | 9.1.1 |
| Display de pruebas | Xvfb; runtime nonroot UID/GID 1000:1000 y sin red |

## Resultados y alcance

| Comprobación | Resultado |
| --- | --- |
| Compilación Meson | 583 targets, sin parches de compatibilidad para Ubuntu 26 |
| Suite Meson | **9 aprobadas, 0 fallos** |
| `task mcp:check` | Ruff sin errores; formato válido; **54 unitarias aprobadas**, 13 nativas excluidas explícitamente |
| Suite Python con `DIA_MCP_NATIVE=1` | **67 aprobadas, 0 fallos**, incluidas 13 de integración/protocolo/regresión nativa |
| Crear/conectar/mover | Figuras nativas, puertos semánticos, cambios de revisión y extremos actualizados |
| Persistencia nativa | `.dia` con tipos, texto Unicode, IDs lógicos en `meta` y dos referencias de conexión; recarga mediante un segundo proceso Dia |
| Exportación | `.dia` y SVG parseados; PNG con CRC, datos descomprimidos y dimensiones válidos |
| MCP real | `initialize`, `tools/list`, llamadas a crear/conectar/exportar, `isError` y continuidad de sesión por stdio de un subproceso |
| Importador Python C | `False` falla; `True` y `None` histórico funcionan; excepción falla |
| Exportador C | Destino no escribible/inexistente devuelve código no cero |
| Atomicidad | Fallos del backend, disco y publicación conservan documento/revisión/archivo anterior; se prueban carreras y symlinks |
| Recursos | Límites de documentos, nodos, conexiones y raster; timeout del worker con error estable |
| Revisión visual | PNG de `examples/workflow.py`: tres figuras con texto legible, dos líneas con flechas y sin recortes |

Las pruebas de conexiones inspeccionan tanto las referencias guardadas como
las posiciones nativas, y vuelven a exportar después de recargar `.dia`.
Las pruebas de contratos usan un backend falso sólo para provocar fallos
controlados; las pruebas marcadas `native` ejecutan Dia real. El tiempo observado
de la suite completa con fuente Python montada fue aproximadamente 8 segundos; es una
observación local, no una garantía de rendimiento.

Artefactos locales del ejemplo, disponibles tras `task mcp:demo`:

| Archivo | Tamaño de la ejecución revisada |
| --- | ---: |
| `artifacts/workflow.dia` | 9273 bytes |
| `artifacts/workflow.svg` | 2278 bytes |
| `artifacts/workflow.png` | 7336 bytes |

Los IDs se generan de nuevo en cada ejecución; el tamaño/hash del archivo
`.dia` no debe usarse como comparación visual ni semántica. Los artefactos son
salidas locales ignoradas por Git; el ejemplo que los genera sí está versionado.

## Reproducir

```sh
task mcp:check
task mcp:build
task mcp:test
task mcp:demo
```

`mcp:build` compila y prueba el código nativo e instala el paquete con sus
dependencias fijadas. `mcp:test` vuelve a comprobar el paquete instalado como
usuario sin privilegios y con red deshabilitada. El workflow
[mcp.yml](../../.github/workflows/mcp.yml) aplica ese mismo aislamiento Ubuntu
en GitHub Actions; consultar sus ejecuciones para el estado de cada commit.
Un resultado local no implica por sí mismo que la ejecución remota haya pasado.

Para ver el detalle Meson del build instalado:

```sh
docker run --rm --init dia-mcp:ubuntu26 cat /opt/dia-build/meson-logs/testlog.txt
```

## Incidencias resueltas durante la validación

- Buildx no pudo escribir en `~/.docker` del entorno administrado: usar
  `DOCKER_CONFIG=/tmp/dia-mcp-dockerconfig`, sin copiar credenciales.
- El binario instalado necesita que el cargador encuentre `/opt/dia/lib`:
  la imagen lo registra con `ldconfig` después de `meson install`.
- Xvfb iniciado como PID 1 podía esperar indefinidamente antes de iniciar el
  programa: `docker run --init` resolvió el arranque. Todos los comandos de
  runtime documentados lo incluyen.
- La primera prueba de protocolo tenía un conflicto entre el nombre del
  helper de prueba y el parámetro `name` de `create_document`; se corrigió el
  helper y se volvió a probar el protocolo completo.
- La revisión detectó que validar sólo firma/dimensiones de PNG era insuficiente:
  se añadieron CRC/descompresión, casos corruptos y límite antes de rasterizar.
- La revisión detectó un `OSError` sin traducir en ediciones: se añadió
  `IO_ERROR` y una prueba de conservación del estado.
- La última revisión extendió esa traducción a la creación del temporal de
  exportación. Un fallo de limpieza se registra en stderr sin ocultar el fallo
  original ni cambiar un resultado ya publicado; tres pruebas cubren esos casos.

## Lo que esta entrega no verifica

La migración GTK4 **no está implementada**. No se afirma paridad GTK4/GTK3,
funcionamiento GUI en Wayland, accesibilidad, IME, impresión, sanitizers ni
rendimiento con miles de objetos. La suite upstream `test-export` sigue sin
estar registrada en Meson; las exportaciones acreditadas son las tres del MVP.
No se han probado todos los tipos de objetos o plugins de Dia.

El smoke test adicional de `samples/render-test.dia` generó un SVG válido,
pero avisó de dos imágenes de muestra ausentes (`dia_logo.png` y
`dia_gnome_icon.png`); no se presenta como verificación visual completa de ese
archivo. El ejemplo propio del MVP no depende de esas imágenes.

APT sigue usando repositorios actualizados, aunque la imagen base y xpm-pixbuf
están fijados. Para reproducibilidad binaria se necesitaría además un snapshot
de paquetes y un registro de imágenes publicadas. El plan GTK4 define las
pruebas adicionales necesarias antes de sustituir el editor.

## Ampliación 0.2: UML, electricidad y neumática (2026-09-19)

- Compilación completa del motor en Ubuntu 26: **9 pruebas Meson aprobadas**.
- Suite ampliada API/nativa/MCP: **103 pruebas aprobadas**.
- Contrato sin GTK: **62 pruebas aprobadas**, 41 nativas excluidas.
- Ruff y comprobación de formato sin errores.
- Persistencia de miembros/parámetros UML, generalización y asociación;
  conexiones técnicas con terminales exactos tras movimiento y recarga.
- Regresión C de direcciones tras inversiones horizontal, vertical y doble,
  restauración y lectura desde `.dia`.
- MCP stdio con propiedades estructuradas, edición, terminales y rechazo de
  índices booleanos sin consumir una revisión.
- Ejemplos `04-uml-pedidos`, `05-mando-electrico` y `06-circuito-neumatico`:
  exportación nativa/SVG/PNG y revisión visual; 6/7, 7/8 y 5/5 nodos/conectores.

Los archivos se generan en `artifacts/engineering` mediante
`task mcp:engineering`; los scripts y las instrucciones están versionados.
[Recorrido de implementación y reproducción](technical-diagrams.md).
