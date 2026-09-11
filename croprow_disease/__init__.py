"""croprow_disease: two-class crop-row plant health detection for a
cultivator-mounted camera.

Classes: ``healthy`` (green, vigorous canopy) and ``unhealthy`` (brown,
yellowed, or otherwise off-colour). Boxes come from the real LettuceMOTS
annotation polygons; the health class is derived from the real pixels those
polygons enclose by the colour rule in ``health.py`` -- an auto-label, not
verified disease ground truth.

Parallel to, and independent of, the single-class ``croprow/`` module and the
potato disease-detection stack in ``ml/`` -- nothing here imports from or
modifies either.
"""

from .health import CLASS_NAMES, HEALTHY, UNHEALTHY, HealthParams

__all__ = ["CLASS_NAMES", "HEALTHY", "UNHEALTHY", "HealthParams"]
