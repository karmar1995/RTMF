# Development from source

For container installation, use [Deploy RTMF](DEPLOYMENT.md). This
page is for contributors who want to run and debug Python services from a
checkout.

## Install

Use Python 3.11+ and a virtual environment:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cp config/rtmf.local.example.json config/rtmf.local.json
```

Edit the local JSON for your endpoints and credentials. It is ignored by Git.
The template uses one PostgreSQL database named `rtmf`. Initialize it with
[`db_mgmt`](INFRASTRUCTURE.md#create-the-account-then-use-db_mgmt) and keep all
database DSNs, including the Slurm worker DSN, pointed at that same database:
jobs and evaluations reference the simulator tables there.
The frontend's Keycloak setup is described in [Keycloak login](KEYCLOAK.md).
Real workflows still need their external services; installing Python dependencies
does not create a database, identity provider, or cluster.

To install the test and packaging tools as well, use
`python -m pip install -e '.[test]'`, then run `python -m pytest tests` from the
checkout root. The distribution test builds a source archive and wheel locally
and checks the installed package from outside the checkout.

## Run a service

```sh
./scripts/run_service_local.py --list-services
./scripts/run_service_local.py parser
./scripts/run_service_local.py analytics
./scripts/run_service_local.py front -- --debug
```

Run each service in its own terminal with the virtual environment activated.
The runner adds `src` to `PYTHONPATH`, uses the repository as its working
directory, and selects `config/rtmf.local.json` when present. To choose a
different file:

```sh
./scripts/run_service_local.py --config /absolute/path/to/runtime.json front
```

For an IDE, select your Python 3.11+ virtual environment as the project
interpreter. The equivalent direct entry point is:

```sh
RTMF_MAIN_CONFIGURATION_FILE=config/rtmf.local.json \
PYTHONPATH=src python -m services.front
```

The local frontend uses HTTP port `5000`; its callback and Keycloak redirect URI
must agree. Production Docker configuration uses the separate deployment
manifest and HTTPS session settings.

Front composes `services.use_case` in-process. Point its `clients.*.base_url`
values at the other local or remote processes. The `use_case` entry point checks
composition and does not expose an HTTP server.
