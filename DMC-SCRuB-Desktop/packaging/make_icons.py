"""Generate the macOS application icon from the Korem Lab logo."""

from __future__ import annotations

import os
import struct
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QSize, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter  # noqa: E402

HERE = Path(__file__).resolve().parent
SOURCE = (
    HERE.parent
    / "src"
    / "dmcscrub_app"
    / "resources"
    / "korem_lab_logo.png"
)
TARGET = HERE / "icon.icns"

ICNS_TYPES: tuple[tuple[bytes, int], ...] = (
    (b"icp4", 16),
    (b"icp5", 32),
    (b"icp6", 64),
    (b"ic07", 128),
    (b"ic08", 256),
    (b"ic09", 512),
    (b"ic10", 1024),
    (b"ic11", 32),
    (b"ic12", 64),
    (b"ic13", 256),
    (b"ic14", 512),
)


def square(source: QImage, size: int) -> QImage:
    """Center the full logo on a transparent square without cropping."""
    canvas = QImage(QSize(size, size), QImage.Format_ARGB32)
    canvas.fill(QColor(0, 0, 0, 0))
    fitted = source.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    painter = QPainter(canvas)
    painter.drawImage(
        (size - fitted.width()) // 2,
        (size - fitted.height()) // 2,
        fitted,
    )
    painter.end()
    return canvas


def png_bytes(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QBuffer.WriteOnly)
    image.save(buffer, "png")
    buffer.close()
    return bytes(data)


def write_icns(source: QImage, target: Path) -> None:
    chunks = b""
    for icon_type, size in ICNS_TYPES:
        blob = png_bytes(square(source, size))
        chunks += icon_type + struct.pack(">I", len(blob) + 8) + blob
    target.write_bytes(b"icns" + struct.pack(">I", len(chunks) + 8) + chunks)


def main() -> int:
    app = QGuiApplication([])
    source = QImage(str(SOURCE))
    if source.isNull():
        raise SystemExit(f"Cannot read icon source: {SOURCE}")
    write_icns(source, TARGET)
    print(f"icon: {TARGET} ({TARGET.stat().st_size / 1024:.0f} KiB)")
    del app
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
