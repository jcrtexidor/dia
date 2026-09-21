/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Synchronous, main-context-only native command transactions.  The temporary
 * UndoStack is discarded or transferred, never retained as a second history. */
#include <config.h>
#include <math.h>
#include <string.h>
#include "pydia-live.h"
#include "pydia-diagram.h"
#include "pydia-object.h"
#include "pydia-layer.h"
#include "undo.h"
#include "object_ops.h"
#include "properties.h"
#include "prop_inttypes.h"
#include "prop_geomtypes.h"
#include "prop_text.h"
#include "connectionpoint.h"
#include "connectionpoint_ops.h"
#include "dia-layer.h"

static GThread *live_main_thread;
static PyObject *live_rollback_error;
static PyObject *live_validation_error;

int
PyDia_LiveExceptionsInit (PyObject *module)
{
  PyObject *exception = PyErr_NewException ("dia.LiveRollbackError", PyExc_RuntimeError, NULL);
  if (!exception) return -1;
  if (PyModule_AddObject (module, "LiveRollbackError", exception) < 0) {
    Py_DECREF (exception);
    return -1;
  }
  /* Keep the native certificate alive even if Python removes the module attribute. */
  Py_INCREF (exception);
  Py_XSETREF (live_rollback_error, exception);
  exception = PyErr_NewException ("dia.LiveValidationError", PyExc_ValueError, NULL);
  if (!exception) return -1;
  if (PyModule_AddObject (module, "LiveValidationError", exception) < 0) {
    Py_DECREF (exception);
    return -1;
  }
  Py_INCREF (exception);
  Py_XSETREF (live_validation_error, exception);
  return 0;
}

static void
certify_rollback (void)
{
  PyObject *type = NULL, *value = NULL, *traceback = NULL;
  PyObject *message = NULL, *certificate = NULL;

  /* Called only after the temporary history has been reversed and restored.
   * Allocation/formatting errors remain ordinary exceptions, hence uncertain. */
  PyErr_Fetch (&type, &value, &traceback);
  PyErr_NormalizeException (&type, &value, &traceback);
  if (PyErr_Occurred ()) goto out;
  if (value && traceback && PyException_SetTraceback (value, traceback) < 0) goto out;
  message = value ? PyObject_Str (value)
                  : PyUnicode_FromString ("Native command transaction was rolled back");
  if (!message) goto out;
  certificate = PyObject_CallFunctionObjArgs (live_rollback_error, message, NULL);
  if (!certificate) goto out;
  if (value) {
    PyException_SetCause (certificate, value); /* steals value */
    value = NULL;
  }
  PyErr_SetObject (live_rollback_error, certificate);

out:
  Py_XDECREF (certificate);
  Py_XDECREF (message);
  Py_XDECREF (traceback);
  Py_XDECREF (value);
  Py_XDECREF (type);
}

void
PyDia_LiveInit (void)
{
  live_main_thread = g_thread_self ();
}

static int
fail (const char *message)
{
  PyErr_SetString (live_validation_error, message);
  return 0;
}

static Diagram *
live_diagram (PyObject *value)
{
  if (g_thread_self () != live_main_thread ||
      !g_main_context_is_owner (g_main_context_default ())) {
    fail ("Native live commands require the GTK main context");
    return NULL;
  }
  if (!PyObject_TypeCheck (value, &PyDiaDiagram_Type)) {
    fail ("Expected a live Diagram");
    return NULL;
  }
  return DIA_DIAGRAM (((PyDiaDiagram *) value)->parent.data);
}

/* Test membership without dereferencing an untrusted/stale object pointer. */
static DiaObject *
live_object (Diagram *dia, PyObject *value)
{
  DiaObject *obj;
  if (!value || !PyObject_TypeCheck (value, &PyDiaObject_Type)) {
    fail ("Expected an object in this diagram");
    return NULL;
  }
  obj = ((PyDiaObject *) value)->object;
  for (int i = 0; i < data_layer_count (dia->data); i++)
    if (g_list_find (dia_layer_get_object_list (data_layer_get_nth (dia->data, i)), obj))
      return obj;
  fail ("Object is no longer a top-level member of this diagram");
  return NULL;
}

static int
number (PyObject *dict, const char *key, double *out)
{
  PyObject *v = PyDict_GetItemString (dict, key);
  if (!v || PyBool_Check (v) || !(PyFloat_Check (v) || PyLong_Check (v)))
    return fail ("Coordinates must be finite numbers");
  *out = PyFloat_AsDouble (v);
  return !PyErr_Occurred () && isfinite (*out) && fabs (*out) <= 1000000
         ? 1 : fail ("Coordinate outside supported range");
}

static int
index_value (PyObject *dict, const char *key, int bound)
{
  PyObject *v = PyDict_GetItemString (dict, key);
  long n;
  if (!v || !PyLong_Check (v) || PyBool_Check (v)) {
    fail ("Handle/connection index must be an integer"); return -1;
  }
  n = PyLong_AsLong (v);
  if (PyErr_Occurred () || n < 0 || n >= bound) {
    fail ("Handle/connection index out of range"); return -1;
  }
  return n;
}

static int
set_properties (Diagram *dia, DiaObject *obj, PyObject *values)
{
  GPtrArray *props = g_ptr_array_new ();
  PyObject *key, *value;
  Py_ssize_t pos = 0;
  const PropDescription *descs;
  if (!values) { prop_list_free (props); return 1; }
  if (!PyDict_CheckExact (values) || PyDict_Size (values) > 64 ||
      !obj->ops->describe_props || !obj->ops->get_props || !obj->ops->set_props) {
    prop_list_free (props); return fail ("Unsupported property set");
  }
  descs = dia_object_describe_properties (obj);
  while (PyDict_Next (values, &pos, &key, &value)) {
    const char *name = PyUnicode_Check (key) ? PyUnicode_AsUTF8 (key) : NULL;
    const PropDescription *d = descs;
    Property *p;
    if (!name || !d) goto invalid;
    while (d->name && strcmp (d->name, name)) d++;
    if (!d->name || (d->flags & (PROP_FLAG_LOAD_ONLY | PROP_FLAG_WIDGET_ONLY)) ||
        (!(d->flags & PROP_FLAG_VISIBLE) && strcmp (d->type, PROP_TYPE_TEXT))) goto invalid;
    /* Only fetch values after the descriptor type has passed the allowlist. */
    if (strcmp (d->type, PROP_TYPE_BOOL) && strcmp (d->type, PROP_TYPE_INT) &&
        strcmp (d->type, PROP_TYPE_ENUM) && strcmp (d->type, PROP_TYPE_REAL) &&
        strcmp (d->type, PROP_TYPE_LENGTH) && strcmp (d->type, PROP_TYPE_FONTSIZE) &&
        strcmp (d->type, PROP_TYPE_STRING) && strcmp (d->type, PROP_TYPE_TEXT)) goto invalid;
    p = object_prop_by_name (obj, name);
    if (!p) goto invalid;
    g_ptr_array_add (props, p);
    if (!strcmp (d->type, PROP_TYPE_BOOL)) {
      if (!PyBool_Check (value)) goto invalid;
      ((BoolProperty *) p)->bool_data = value == Py_True;
    } else if (!strcmp (d->type, PROP_TYPE_INT) || !strcmp (d->type, PROP_TYPE_ENUM)) {
      long n;
      if (!PyLong_Check (value) || PyBool_Check (value)) goto invalid;
      n = PyLong_AsLong (value);
      if (PyErr_Occurred () || n < G_MININT || n > G_MAXINT) goto invalid;
      if (!strcmp (d->type, PROP_TYPE_ENUM)) {
        const PropEnumData *e = d->extra_data;
        if (!e) goto invalid;
        while (e->name && e->enumv != n) e++;
        if (!e->name) goto invalid;
        ((EnumProperty *) p)->enum_data = n;
      } else {
        const PropNumData *range = d->extra_data;
        if (range && (n < range->min || n > range->max)) goto invalid;
        ((IntProperty *) p)->int_data = n;
      }
    } else if (!strcmp (d->type, PROP_TYPE_STRING) || !strcmp (d->type, PROP_TYPE_TEXT)) {
      Py_ssize_t size;
      const char *s = PyUnicode_Check (value) ? PyUnicode_AsUTF8AndSize (value, &size) : NULL;
      if (!s || size > 65536 || (Py_ssize_t) strlen (s) != size) goto invalid;
      if (!strcmp (d->type, PROP_TYPE_TEXT)) {
        g_free (((TextProperty *) p)->text_data);
        ((TextProperty *) p)->text_data = g_strdup (s);
      } else {
        g_free (((StringProperty *) p)->string_data);
        ((StringProperty *) p)->string_data = g_strdup (s);
      }
    } else {
      double n;
      const PropNumData *range = d->extra_data;
      if (PyBool_Check (value) || !(PyFloat_Check (value) || PyLong_Check (value))) goto invalid;
      n = PyFloat_AsDouble (value);
      if (PyErr_Occurred () || !isfinite (n) || fabs (n) > 1000000 ||
          (range && (n < range->min || n > range->max))) goto invalid;
      if (!strcmp (d->type, PROP_TYPE_LENGTH)) ((LengthProperty *) p)->length_data = n;
      else if (!strcmp (d->type, PROP_TYPE_FONTSIZE)) ((FontsizeProperty *) p)->fontsize_data = n;
      else ((RealProperty *) p)->real_data = n;
    }
  }
  if (props->len) {
    object_add_updates (obj, dia);
    dia_object_change_change_new (dia, obj, object_apply_props (obj, props));
    object_add_updates (obj, dia);
    diagram_update_connections_object (dia, obj, TRUE);
  }
  prop_list_free (props);
  return 1;
invalid:
  prop_list_free (props);
  return fail ("Property is unsupported, read-only, or its value is outside its descriptor range");
}

static int
command (Diagram *dia, PyObject *cmd, PyObject *created)
{
  PyObject *opv;
  const char *op;
  DiaObject *obj;
  DiaChange *change;
  if (!PyDict_CheckExact (cmd)) return fail ("Command must be a dict");
  opv = PyDict_GetItemString (cmd, "op");
  op = opv && PyUnicode_Check (opv) ? PyUnicode_AsUTF8 (opv) : NULL;
  if (!op) return fail ("Command requires op");
  if (!strcmp (op, "create")) {
    PyObject *typev = PyDict_GetItemString (cmd, "type");
    PyObject *layerv = PyDict_GetItemString (cmd, "layer");
    const char *name = typev && PyUnicode_Check (typev) ? PyUnicode_AsUTF8 (typev) : NULL;
    DiaObjectType *type = name ? object_get_type ((char *) name) : NULL;
    DiaLayer *layer = dia_diagram_data_get_active_layer (dia->data);
    Point p;
    Handle *h1 = NULL, *h2 = NULL;
    PyObject *wrapper;
    if (!type || !type->ops || !type->ops->create) return fail ("Unknown installed object type");
    if (!number (cmd, "x", &p.x) || !number (cmd, "y", &p.y)) return 0;
    if (layerv && layerv != Py_None) {
      if (!PyObject_TypeCheck (layerv, &PyDiaLayer_Type)) return fail ("Expected layer");
      layer = ((PyDiaLayer *) layerv)->layer;
      if (data_layer_get_index (dia->data, layer) < 0) return fail ("Layer belongs to another diagram");
    }
    obj = type->ops->create (&p, type->default_user_data, &h1, &h2);
    if (!obj) return fail ("Object creation failed");
    data_set_active_layer (dia->data, layer);
    change = dia_insert_objects_change_new (dia, g_list_append (NULL, obj), FALSE);
    dia_change_apply (change, dia->data);
    if (!set_properties (dia, obj, PyDict_GetItemString (cmd, "properties"))) return 0;
    wrapper = PyDiaObject_New (obj);
    if (!wrapper) return 0;
    int result = PyList_Append (created, wrapper);
    Py_DECREF (wrapper);
    return result == 0;
  }
  if (!strcmp (op, "layout")) {
    PyObject *items = PyDict_GetItemString (cmd, "objects");
    PyObject *modev = PyDict_GetItemString (cmd, "mode");
    const char *mode = modev && PyUnicode_Check (modev) ? PyUnicode_AsUTF8 (modev) : NULL;
    const char *modes[] = {"left", "center", "right", "distribute_horizontal", "top", "middle", "bottom", "distribute_vertical"};
    int m;
    GList *objects = NULL;
    if (!mode || !items || !PyList_CheckExact (items) || PyList_Size (items) < 2 || PyList_Size (items) > 64)
      return fail ("Layout requires 2..64 objects and a native layout mode");
    for (m = 0; m < 8 && strcmp (mode, modes[m]); m++);
    if (m == 8) return fail ("Unsupported native layout mode");
    for (Py_ssize_t i = 0; i < PyList_Size (items); i++) {
      obj = live_object (dia, PyList_GetItem (items, i));
      if (!obj || g_list_find (objects, obj)) { g_list_free (objects); return fail ("Invalid/duplicate layout object"); }
      objects = g_list_append (objects, obj);
    }
    if (m < 4) object_list_align_h (objects, dia, m == 3 ? DIA_ALIGN_EQUAL : m);
    else object_list_align_v (objects, dia, m == 7 ? DIA_ALIGN_EQUAL : m - 4);
    g_list_free (objects);
    return 1;
  }
  obj = live_object (dia, PyDict_GetItemString (cmd, "object"));
  if (!obj) return 0;
  if (!strcmp (op, "move")) {
    Point dest;
    Point *before, *after;
    if (!number (cmd, "x", &dest.x) || !number (cmd, "y", &dest.y)) return 0;
    before = g_new (Point, 1); after = g_new (Point, 1);
    *before = obj->position; *after = dest;
    change = dia_move_objects_change_new (dia, before, after, g_list_append (NULL, obj));
    dia_change_apply (change, dia->data);
  } else if (!strcmp (op, "set_properties")) {
    PyObject *values = PyDict_GetItemString (cmd, "properties");
    if (!values) return fail ("Missing properties");
    return set_properties (dia, obj, values);
  } else if (!strcmp (op, "delete")) {
    if (obj->parent || obj->children) return fail ("Deleting parented objects is unsupported");
    for (int i = 0; i < obj->num_handles; i++)
      if (obj->handles[i]->connected_to) return fail ("Disconnect object before deletion");
    for (int i = 0; i < obj->num_connections; i++)
      if (obj->connections[i]->connected) return fail ("Disconnect attached objects before deletion");
    data_set_active_layer (dia->data, dia_object_get_parent_layer (obj));
    change = dia_delete_objects_change_new (dia, g_list_append (NULL, obj));
    dia_change_apply (change, dia->data);
  } else if (!strcmp (op, "connect") || !strcmp (op, "disconnect")) {
    int h = index_value (cmd, "handle", obj->num_handles);
    if (h < 0) return 0;
    if (!strcmp (op, "connect")) {
      DiaObject *target = live_object (dia, PyDict_GetItemString (cmd, "target"));
      int p = target ? index_value (cmd, "point", target->num_connections) : -1;
      if (p < 0) return 0;
      if (obj == target || obj->handles[h]->connect_type == HANDLE_NONCONNECTABLE)
        return fail ("Handle cannot connect to this target");
      if (obj->handles[h]->connected_to)
        dia_change_apply (dia_unconnect_change_new (dia, obj, obj->handles[h]), dia->data);
      dia_change_apply (dia_connect_change_new (dia, obj, obj->handles[h], target->connections[p]), dia->data);
    } else if (obj->handles[h]->connected_to) {
      dia_change_apply (dia_unconnect_change_new (dia, obj, obj->handles[h]), dia->data);
    }
  } else return fail ("Unsupported native command");
  return 1;
}

PyObject *
PyDia_LiveApply (PyObject *self, PyObject *args)
{
  PyObject *value, *commands, *created, *result;
  Diagram *dia;
  UndoStack *original, *stage;
  DiaChange *base, *change;
  DiaLayer *layer;
  GList *selection;
  int ok = 1;
  if (!PyArg_ParseTuple (args, "OO:live_apply", &value, &commands)) return NULL;
  dia = live_diagram (value);
  if (!dia) return NULL;
  if (!PyList_CheckExact (commands) || PyList_Size (commands) < 1 || PyList_Size (commands) > 64) {
    fail ("Expected 1..64 commands"); return NULL;
  }
  created = PyList_New (0);
  if (!created) return NULL;
  result = Py_BuildValue ("{s:O}", "created", created);
  if (!result) { Py_DECREF (created); return NULL; }
  original = dia->undo;
  if (!DIA_IS_TRANSACTION_POINT_CHANGE (original->current_change)) {
    Py_DECREF (created); Py_DECREF (result);
    fail ("A native UI transaction is still in progress"); return NULL;
  }
  stage = new_undo_stack (dia);
  base = stage->current_change;
  layer = dia_diagram_data_get_active_layer (dia->data);
  selection = g_list_copy (dia->data->selected);
  dia->undo = stage;
  for (Py_ssize_t i = 0; i < PyList_Size (commands); i++) {
    ok = command (dia, PyList_GetItem (commands, i), created);
    data_set_active_layer (dia->data, layer);
    if (!ok) break;
  }
  if (!ok) {
    /* Reverse every applied change without creating/pruning transaction marks. */
    for (change = stage->current_change; change != base; change = change->prev)
      dia_change_revert (change, dia->data);
    stage->current_change = base;
    data_remove_all_selected (dia->data);
    for (GList *l = selection; l; l = l->next) data_select (dia->data, l->data);
  }
  dia->undo = original;
  if (ok && base->next) {
    change = base->next;
    base->next = NULL;
    stage->current_change = stage->last_change = base;
    while (change) {
      DiaChange *next = change->next;
      undo_push_change (original, change);
      change = next;
    }
    undo_set_transactionpoint (original);
    diagram_set_modified (dia, TRUE);
  }
  /* undo_destroy does not release its initial marker. */
  undo_destroy (stage);
  dia_change_unref (base);
  data_set_active_layer (dia->data, layer);
  g_list_free (selection);
  diagram_update_extents (dia);
  diagram_add_update_all (dia);
  diagram_flush (dia);
  Py_DECREF (created);
  if (!ok) {
    Py_DECREF (result);
    certify_rollback ();
    return NULL;
  }
  return result;
}

PyObject *
PyDia_LiveHistory (PyObject *self, PyObject *args)
{
  PyObject *value;
  const char *direction;
  Diagram *dia;
  gboolean undo;
  if (!PyArg_ParseTuple (args, "Os:live_history", &value, &direction)) return NULL;
  dia = live_diagram (value);
  if (!dia) return NULL;
  if (strcmp (direction, "undo") && strcmp (direction, "redo")) {
    fail ("History direction must be undo or redo"); return NULL;
  }
  undo = !strcmp (direction, "undo");
  if (!DIA_IS_TRANSACTION_POINT_CHANGE (dia->undo->current_change)) {
    fail ("A native UI transaction is still in progress"); return NULL;
  }
  if (!undo_available (dia->undo, undo) ||
      (undo && !dia->undo->current_change->prev)) Py_RETURN_FALSE;
  if (undo) undo_revert_to_last_tp (dia->undo);
  else undo_apply_to_next_tp (dia->undo);
  diagram_set_modified (dia, !undo_is_saved (dia->undo));
  diagram_update_extents (dia);
  diagram_add_update_all (dia);
  diagram_flush (dia);
  Py_RETURN_TRUE;
}
