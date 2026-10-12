# Dia operations MCP — versión 0.3.0 del fork

Integración local `stdio` con el SDK MCP 1.30.0, separada del Python embebido de
Dia. El editor conserva GTK3, Meson, su modelo, historial y serialización nativos.

- **Live:** inspección de la GUI, selección, contexto, planes, validación estática,
  transacciones nativas y archivos, con acceso explícito y generaciones/recibos.
- **Snapshot:** creación y exportación aisladas, con catálogo de creación acotado;
  sus IDs y cambios no modifican la ventana abierta.

La versión ofrece 37 herramientas, cuatro recursos concretos, una plantilla de
recurso y dos prompts. Los dominios semánticos son auxiliares opcionales; objetos
instalados desconocidos para MCP siguen disponibles mediante operaciones genéricas.

## Instalar y usar

Para Ubuntu 26.04 amd64, usar el paquete `.deb` y sus lanzadores `dia-fork`,
`dia-mcp` y `dia-mcp-config`. MCP está desactivado inicialmente. No hace falta el
checkout ni configurar PYTHONPATH para la instalación del usuario.

- [Instalación y cliente MCP](../docs/installation.md)
- [Guía de uso](../docs/user-guide.md)
- [Herramientas y flujos de selección](../docs/mcp-tools.md)
- [Problemas y recuperación](../docs/troubleshooting.md)
- [Seguridad y modos de acceso](../docs/security.md)

## Desarrollo y validación

```sh
./build-aux/mcp/bootstrap.sh   # desde la raíz del repo; Docker disponible
# Con Task y uv:
task mcp:check
task mcp:build
task mcp:test
task mcp:release-check
```

Las dependencias se conservan en `uv.lock` y `requirements.lock`; no modificar el
Python global. El contenedor compila Dia e incluye pruebas nativas; las pruebas
portables no las sustituyen. La automatización genera artefactos locales y no
publica releases.

- [Desarrollo](../docs/mcp-development.md) y [contenedor](../build-aux/mcp/README.md)
- [Arquitectura](../docs/mcp-architecture.md) y [progreso](../docs/progress.md)
- [Hitos M8–M10](../docs/m8-m10-roadmap.md), [versiones y release](../docs/release-validation.md)
- [Aceptación con usuario limpio](../docs/user-acceptance.md)

Las limitaciones de codecs compuestos, grupos, rutas de archivos y simulación se
explicitan en las herramientas/documentación. No se exponen eval, shell ni carga
remota de plugins. Plugins/documentos nativos se ejecutan dentro de la confianza
del usuario local, no en una sandbox de seguridad.

## Contribuir a este fork

Seguir [la guía del fork](../docs/modernization/contributing.md). Upstream
GNOME/dia no acepta contribuciones generadas con IA; este trabajo asistido se
mantiene en `jcrtexidor/dia`, con su origen documentado y licencia GPL.
