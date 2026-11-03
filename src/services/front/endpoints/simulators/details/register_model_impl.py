import re

from flask import current_app, render_template, request, redirect, url_for

from use_case_contracts.messages import (
    DotnetSpec,
    JavaSpec,
    PackageSpec,
    ParameterSpec,
    PlatformSpec,
    PythonSpec,
    RegisterSimulator,
    ModelFileSpec,
    OpenRegisterSimulatorForm,
    TechnologySpec,
)

def register_model():
    if request.method == "POST":
        payload = _parse_register_form()
        model_name = payload.get("model_name") or ""
        _submit_registration(payload)
        return redirect(url_for("onSimulatorRegistrationMonitor"))

    usecases = current_app.extensions.get("usecases")
    if usecases is not None:
        usecases.handle(OpenRegisterSimulatorForm())
    return render_template("register_model.html", active_page="register_model")


def _parse_register_form():
    form = request.form
    files = request.files

    payload = {
        "model_name": (form.get("modelName") or "").strip(),
        "platform": _parse_platform(form),
        "technology": _parse_technology(form, files),
        "input_params": _parse_indexed_group(form, "inputParams", ("name", "type")),
        "output_params": _parse_indexed_group(form, "outputParams", ("name", "type")),
    }

    model_file = files.get("modelFile")
    if model_file is not None and model_file.filename:
        payload["model_file"] = {
            "filename": model_file.filename,
            "content_type": model_file.mimetype,
            "bytes": model_file.read(),
        }
        model_file.stream.seek(0)

    return payload


def _submit_registration(payload):
    usecases = current_app.extensions.get("usecases")
    if usecases is None:
        return

    platform = payload.get("platform") or {}
    tech = payload.get("technology") or {}
    input_params = payload.get("input_params") or []
    output_params = payload.get("output_params") or []

    message = RegisterSimulator(
        name=payload.get("model_name") or "",
        platform=PlatformSpec(
            os=platform.get("os", "linux"),
            arch=platform.get("arch", "amd64")
        ),
        technology=_build_technology_spec(tech),
        input_params=[ParameterSpec(**item) for item in input_params],
        output_params=[ParameterSpec(**item) for item in output_params],
        model_file=_build_model_file_spec(payload.get("model_file")),
    )
    usecases.handle(message)


def _parse_platform(form):
    platform = {}
    os_name = (form.get("platform[os]") or "").strip()
    arch = (form.get("platform[arch]") or "").strip()
    variant = (form.get("platform[variant]") or "").strip()
    if os_name:
        platform["os"] = os_name
    if arch:
        platform["arch"] = arch
    if variant:
        platform["variant"] = variant
    return platform


def _parse_technology(form, files):
    tech_type = (form.get("technology[type]") or "").strip()
    tech = {"type": tech_type} if tech_type else {}

    if tech_type == "python":
        python_cfg = _strip_empty({
            "version": form.get("technology[python][version]"),
        })
        venv_value = form.get("technology[python][venv]")
        if venv_value is not None:
            python_cfg["venv"] = _parse_bool(venv_value)
        manual_packages = _parse_indexed_group(
            form,
            "technology[python][packages]",
            ("name", "version"),
            drop_empty_name=True
        )
        requirements_packages, requirements_filename = _parse_requirements_upload(files)
        if requirements_filename:
            python_cfg["requirements_upload"] = requirements_filename

        merged_packages = _merge_packages(requirements_packages, manual_packages)
        if merged_packages:
            python_cfg["packages"] = merged_packages
        if python_cfg:
            tech["python"] = python_cfg

    if tech_type == "java":
        java_cfg = _strip_empty({
            "distribution": form.get("technology[java][distribution]"),
            "version": form.get("technology[java][version]"),
            "app_type": form.get("technology[java][app_type]"),
        })
        if java_cfg:
            tech["java"] = java_cfg

    if tech_type == "dotnet":
        dotnet_cfg = _strip_empty({
            "version": form.get("technology[dotnet][version]"),
            "flavor": form.get("technology[dotnet][flavor]"),
        })
        if dotnet_cfg:
            tech["dotnet"] = dotnet_cfg

    return tech


def _build_technology_spec(tech):
    tech_type = tech.get("type") or "python"
    python_cfg = tech.get("python") or {}
    java_cfg = tech.get("java") or {}
    dotnet_cfg = tech.get("dotnet") or {}

    python_spec = None
    if tech_type == "python":
        packages = [
            PackageSpec(name=p.get("name"), version=p.get("version") or None)
            for p in (python_cfg.get("packages") or [])
            if p.get("name")
        ]
        python_spec = PythonSpec(
            version=python_cfg.get("version") or None,
            packages=packages or None
        )

    java_spec = None
    if tech_type == "java":
        java_spec = JavaSpec(
            distribution=java_cfg.get("distribution") or None,
            version=java_cfg.get("version") or None,
            app_type=java_cfg.get("app_type") or None,
        )

    dotnet_spec = None
    if tech_type == "dotnet":
        dotnet_spec = DotnetSpec(
            version=dotnet_cfg.get("version") or None,
            flavor=dotnet_cfg.get("flavor") or None,
        )

    return TechnologySpec(
        type=tech_type,
        python=python_spec,
        java=java_spec,
        dotnet=dotnet_spec,
    )


def _build_model_file_spec(model_file):
    if not model_file:
        return None
    return ModelFileSpec(
        filename=model_file.get("filename", ""),
        content_type=model_file.get("content_type"),
        bytes=model_file.get("bytes", b""),
    )


def _parse_requirements_upload(files):
    upload = files.get("pythonRequirementsFile")
    if upload is None or not upload.filename:
        return [], ""

    try:
        raw = upload.read().decode("utf-8", errors="ignore")
    finally:
        upload.stream.seek(0)

    packages = []
    for line in raw.splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        name, version = _split_requirement(text)
        if name:
            packages.append(_strip_empty({"name": name, "version": version}))

    return packages, upload.filename


def _split_requirement(text):
    if "==" in text:
        name, version = text.split("==", 1)
        return name.strip(), version.strip()
    return text.strip(), ""


def _merge_packages(requirements_packages, manual_packages):
    by_name = {}
    for pkg in requirements_packages:
        name = pkg.get("name")
        if name:
            by_name[name] = pkg
    for pkg in manual_packages:
        name = pkg.get("name")
        if name:
            by_name[name] = pkg
    return list(by_name.values())


def _parse_indexed_group(form, group_name, fields, drop_empty_name=False):
    pattern = re.compile(rf"^{re.escape(group_name)}\[(\d+)\]\[([^\]]+)\]$")
    by_index = {}
    for key, value in form.items():
        match = pattern.match(key)
        if not match:
            continue
        idx = int(match.group(1))
        field = match.group(2)
        if field not in fields:
            continue
        by_index.setdefault(idx, {})[field] = (value or "").strip()

    items = []
    for idx in sorted(by_index.keys()):
        item = {field: by_index[idx].get(field, "") for field in fields}
        if drop_empty_name and not item.get("name"):
            continue
        if all(not val for val in item.values()):
            continue
        items.append(_strip_empty(item))
    return items


def _strip_empty(values):
    return {key: value.strip() for key, value in values.items() if value and value.strip()}


def _parse_bool(value):
    text = str(value).strip().lower()
    return text in ("1", "true", "yes", "on")
