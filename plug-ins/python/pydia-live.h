/* SPDX-License-Identifier: GPL-2.0-or-later */
#pragma once
#include <Python.h>
void PyDia_LiveInit (void);
PyObject *PyDia_LiveApply (PyObject *self, PyObject *args);
PyObject *PyDia_LiveHistory (PyObject *self, PyObject *args);
