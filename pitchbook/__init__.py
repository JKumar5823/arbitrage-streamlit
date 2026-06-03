"""PitchBook capture room.

A locally-run control panel that drives your real cursor, captures
screenshots of PitchBook, extracts structured data from them with Claude
vision (Tesseract OCR fallback), and stores the results in a cloud SQL
database.

NOTE: cursor control and screen capture only work when this package runs on
your own machine (with a display attached). The heavy desktop dependencies
are imported lazily so the package still imports cleanly in headless/CI
environments.
"""

__all__ = ["cursor", "extract", "storage"]
