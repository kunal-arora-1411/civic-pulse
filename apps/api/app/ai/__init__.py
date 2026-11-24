"""Vision and similarity models behind a small, testable interface.

Everything in this package is pure computation: no database, no Celery, no
HTTP. Domain code depends on the protocols in ``interfaces`` and obtains an
implementation from ``get_vision_model()``; tests use the deterministic fake.
"""
