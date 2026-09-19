/* Live file operations use native serializers, never snapshot reconstruction. */
#include "config.h"
#include <Python.h>
#include <string.h>
#include "pydia-diagram.h"
#include "pydia-live-files.h"
#include "app/display.h"
#include "app/load_save.h"
#include "app/undo.h"
#include "app/recent_files.h"

static GThread *live_files_thread;

void
PyDia_LiveFilesInit (void)
{
  live_files_thread = g_thread_self ();
}

PyObject *
PyDia_LiveFile (PyObject *self, PyObject *args)
{
  const char *op, *path, *format, *logical;
  PyObject *wrapper;
  Diagram *diagram;
  DiaExportFilter *filter;
  DiaContext *ctx;
  gboolean ok;
  GFile *file;

  if (g_thread_self () != live_files_thread ||
      !g_main_context_is_owner (g_main_context_default ()))
    return PyErr_Format (PyExc_RuntimeError, "Native files require the GTK main context");
  if (!PyArg_ParseTuple (args, "sOsss:live_file", &op, &wrapper,
                         &path, &format, &logical))
    return NULL;
  if (strcmp (op, "open") == 0) {
    /* A failed import must not partially replace the editor's default diagram. */
    file = g_file_new_for_path (path);
    diagram = dia_diagram_new (file);
    g_object_unref (file);
    if (!diagram || !diagram_load_into (diagram, path, &dia_import_filter)) {
      if (diagram) diagram_destroy (diagram);
      return PyErr_Format (PyExc_IOError, "Native diagram import failed");
    }
    diagram_set_modified (diagram, FALSE);
    new_display (diagram);
    recent_file_history_add (path);
    return PyDiaDiagram_New (diagram);
  }
  if (!PyObject_TypeCheck (wrapper, &PyDiaDiagram_Type))
    return PyErr_Format (PyExc_TypeError, "Expected a live Diagram");
  diagram = (Diagram *) ((PyDiaDiagram *) wrapper)->parent.data;
  if (strcmp (op, "commit") == 0) {
    file = g_file_new_for_path (logical);
    dia_diagram_set_file (diagram, file);
    g_object_unref (file);
    diagram->unsaved = FALSE;
    undo_mark_save (diagram->undo);
    diagram_set_modified (diagram, FALSE);
    diagram_cleanup_autosave (diagram);
    recent_file_history_add (logical);
    Py_RETURN_NONE;
  }
  if (strcmp (op, "stage") != 0)
    return PyErr_Format (PyExc_ValueError, "Unknown native file operation");
  if (strcmp (format, "dia") == 0)
    filter = &dia_export_filter;
  else if (strcmp (format, "svg") == 0)
    filter = filter_export_get_by_name ("dia-svg");
  else if (strcmp (format, "png") == 0)
    filter = filter_guess_export_filter ("live.png");
  else
    return PyErr_Format (PyExc_ValueError, "Unsupported live export format");
  if (!filter)
    return PyErr_Format (PyExc_RuntimeError, "Requested native export filter unavailable");
  diagram_update_extents (diagram);
  ctx = dia_context_new ("Live file export");
  /* Physical temporary location differs from logical resource-relative base. */
  dia_context_set_filename (ctx, logical);
  ok = filter->export_func (diagram->data, ctx, path, diagram->filename,
                            filter->user_data);
  /* Return structured failure through Python instead of opening a modal dialog. */
  dia_context_reset (ctx);
  dia_context_release (ctx);
  if (!ok)
    return PyErr_Format (PyExc_IOError, "Native serialization failed");
  Py_RETURN_NONE;
}
