"""Configuración común de las pruebas."""

from __future__ import annotations

import pytest

from core.historial import VARIABLE_DATOS


@pytest.fixture(autouse=True)
def datos_aislados(tmp_path_factory, monkeypatch):
    """Ninguna prueba escribe en el historial real del usuario: cada una usa el suyo."""
    carpeta = tmp_path_factory.mktemp("datos-del-programa")
    monkeypatch.setenv(VARIABLE_DATOS, str(carpeta))
    return carpeta
