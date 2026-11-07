from __future__ import annotations

def main() -> None:
    """Start the desktop application."""
    from dmcscrub_app.app import run

    raise SystemExit(run())


if __name__ == "__main__":
    main()
