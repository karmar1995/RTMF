from __future__ import annotations

from services.simulators_repository.rest_api.container import RestRepositoryServiceContainer


def main() -> None:
    container = RestRepositoryServiceContainer()
    container.composition().initialize()
    container.run()


if __name__ == "__main__":
    main()
