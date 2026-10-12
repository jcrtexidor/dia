# Contribuir al fork de automatización

Este trabajo vive en [jcrtexidor/dia](https://github.com/jcrtexidor/dia), a partir
del espejo oficial [GNOME/dia](https://github.com/GNOME/dia). El upstream
autoritativo está en GitLab GNOME. La base de esta entrega es
`ad68cc378b7a187706bc2648c48b44d16fb80819`.

Las adiciones de este fork se desarrollaron con asistencia de IA por solicitud
de su propietario. Se mantienen licencias y atribuciones originales; el módulo
nuevo declara GPL-2.0-or-later. La política upstream rechaza contribuciones
generadas con IA, incluidos documentación e issues. Dirigir propuestas de este
trabajo al fork; no enviar sus parches, issues o solicitudes de soporte a GNOME.

## Registro de implementación — 18 de septiembre de 2026

1. **Identificar la fuente.** Se clonó el espejo GNOME/dia, se registró el SHA
   basal y se revisaron `README.md`, `HACKING.md`, `BUILDING.md` y Meson. El
   código actual usa GTK3; no se partió de documentación antigua sobre GTK2.
2. **Auditar arquitectura.** Se localizaron modelos, renderizadores, capas,
   plugins, CLI y wrappers PyDia. El módulo `dia` es embebido y no independiente;
   no es seguro compartir sus punteros entre procesos o hilos. Los hallazgos y
   referencias están en [source-audit.md](source-audit.md).
3. **Crear el fork.** Se verificó la cuenta `jcrtexidor` y se creó un fork real
   de GNOME/dia. El checkout usa `upstream` para GNOME y `origin` para el fork;
   la autoría Git se configuró localmente. El trabajo se aisló inicialmente en
   `feature/operations-mcp` para revisión antes de integrarlo en el fork.
4. **Definir la frontera.** API externa con contratos JSON tipados y proceso
   Dia por materialización. El SDK MCP queda fuera del intérprete embebido.
   Esta decisión conserva el motor nativo y evita introducir concurrencia en
   PyDia; su coste es reconstruir el snapshot por operación.
5. **Implementar el contrato.** IDs estables, revisiones, dimensiones en cm,
   texto, tres tipos de figura y puertos semánticos. Añadir movimiento permitió
   verificar continuidad de conexiones. El contrato completo y su evolución
   están en [api.md](api.md).
6. **Adaptar PyDia.** Un arranque dedicado registra un importador JSON; después
   de cargar plugins, éste crea objetos, aplica propiedades, añade a la capa,
   mueve handles y conecta puntos. Guarda IDs en la propiedad nativa `meta`.
7. **Corregir propagación de fallos.** `PyDia_import_data` ahora evalúa el retorno
   antes de liberar su referencia; rechaza `False` y excepciones, conservando
   `None` de importadores históricos. `do_convert` comprueba el resultado del
   exportador y termina con código no cero cuando falla.
8. **Exponer MCP.** Ocho herramientas por `stdio` con esquemas del SDK oficial,
   errores del dominio y anotaciones de lectura/escritura. Ninguna herramienta
   acepta Python, shell, archivos de plugin o propiedades arbitrarias.
9. **Construir Ubuntu 26.** Imagen fijada por digest, xpm-pixbuf fijado por SHA,
   dependencias SDK con hashes, compilación Meson y pruebas. Se resolvieron
   restricciones de escritura de Buildx usando `DOCKER_CONFIG` temporal,
   y el arranque de Xvfb como PID 1 usando `docker run --init`.
10. **Revisar y probar.** Pruebas independientes de rollback/archivos/IDs,
    circuito nativo con recarga `.dia`, protocolo MCP real, límites de PNG,
    timeout y regresiones C. Se revisó visualmente el PNG del ejemplo.
    [validation.md](validation.md) identifica qué se verificó y qué queda fuera.
11. **Preparar continuidad.** Task ofrece comandos públicos; GitHub Actions
    recompila y prueba el fork dentro de Ubuntu 26. Documentación de arquitectura,
    API, instalación, decisiones, límites y plan GTK4 queda junto al código.

## Flujo para un cambio nuevo

1. Leer el contrato y elegir una necesidad concreta. Mantener cambios de GTK4
   separados de ampliaciones MCP salvo que compartan una dependencia necesaria.
2. Reproducir el fallo o ejemplo usando `task mcp:build`, `task mcp:test` y el
   consumidor Python o cliente MCP apropiado. Conservar el caso fallido.
3. Modificar `models.py`/`service.py` para reglas del dominio, `native/bridge.py`
   para adaptaciones PyDia, `backend.py` para procesos/archivos y `server.py`
   para transporte. Cambiar C sólo cuando el motor lo requiera.
4. Añadir una prueba del comportamiento observable. Un backend falso sirve
   para rollback; no sustituye a Dia para geometría, conexiones o exportación.
   Si se añade una herramienta, probarla por un cliente MCP real.
5. Ejecutar `task mcp:check`; reconstruir y ejecutar `task mcp:test` para cambios
   nativos o dependencias. Para geometría, generar un ejemplo nuevo y revisarlo
   visualmente. El build ya ejecuta las pruebas Meson y de MCP.
6. Actualizar contrato, capacidades, límites y guía. Regenerar el esquema si
   cambia `Document`; actualizar `uv.lock` y el export con hashes si cambian
   dependencias. Verificar que la imagen use el mismo contrato publicado.
7. Revisar el diff, confirmar que no incluye credenciales, `.venv`, artefactos
   temporales ni cambios ajenos y publicar commits en el fork. Las revisiones
   deben indicar caso resuelto, validación ejecutada y limitaciones restantes.

## Actualizar dependencias y esquema

Desde la raíz, después de modificar deliberadamente `mcp/pyproject.toml`:

```sh
uv lock --directory mcp
uv export --directory mcp --locked --no-dev --no-emit-project \
  --format requirements-txt --output-file requirements.lock
uv run --directory mcp python -c 'import json; from pathlib import Path; from dia_mcp.models import Document; Path("../docs/modernization/document.schema.json").write_text(json.dumps(Document.model_json_schema(), indent=2) + "\n")'
```

El contenedor instala el export con `--require-hashes` y el paquete local con
`--no-deps`. La base Ubuntu, el subproyecto nativo y el SDK están fijados; APT
continúa recibiendo actualizaciones. Registrar versiones nuevas y ejecutar la
suite cuando se actualice cualquiera de esos componentes.

## Siguientes contribuciones delimitadas

- Persistencia/restauración de snapshots de sesión con validación de versión.
- Importar `.dia` preservando tipos y propiedades no incluidos en este MVP.
- Operaciones por lotes para reducir el coste de reconstrucción.
- Conectores ortogonales, estilos y propiedades adicionales, siempre tipados.
- Primeras fases GTK3 del [plan GTK4](gtk4-migration.md): separar comandos,
  entrada y editores de propiedades antes del cambio de toolkit.

El objetivo de la siguiente fase GTK4 es un prototipo verificable del lienzo,
no declarar migrado el editor cambiando la dependencia de Meson.
