from __future__ import annotations

from services.analytics.composition.composition_root import build_app


def main() -> None:
    build_app().run()


if __name__ == "__main__":
    main()
