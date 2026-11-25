from __future__ import annotations

import sys

from dmcscrub_app.backend.paths import BACKEND_FLAG


def main() -> None:
    """Start the GUI, or run one backend request inside the frozen executable."""
    if len(sys.argv) == 3 and sys.argv[1] == BACKEND_FLAG:
        from dmcscrub_app.backend.process_main import main as run_backend_process

        raise SystemExit(run_backend_process([sys.argv[0], sys.argv[2]]))

    from dmcscrub_app.app import run

    raise SystemExit(run())


if __name__ == "__main__":
    main()
