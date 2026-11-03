from dataclasses import dataclass


@dataclass(frozen=True)
class BaseImageCatalog:
    python_prefix: str
    java_prefix: str
    native_image: str

    def __post_init__(self) -> None:
        for field_name, value in (
            ("python_prefix", self.python_prefix),
            ("java_prefix", self.java_prefix),
            ("native_image", self.native_image),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")


class DockerfileDirector:
    """
    Director that renders a Dockerfile from a structured configuration dict.

    Expected config format:
    {
      "platform": {
          "os": "linux",
          "arch": "amd64"
      },
      "technology": {
          "type": "python",
          "python": {
              "version": str(opt),
              "packages": [{"name": str, "version": str(opt)}](opt)
          }
      },
      "artifacts": {
          "zip": {
              "path": str,
              "strip_root": bool(opt)
          }
      }
    }
    """

    def __init__(self, builder, base_image_catalog: BaseImageCatalog):
        if builder is None:
            raise ValueError("builder is required")
        if base_image_catalog is None:
            raise ValueError("base_image_catalog is required")
        self._builder = builder
        self._base_images = base_image_catalog

    def render(self, config):
        if not isinstance(config, dict):
            raise ValueError("config must be a dict")

        self._assert_allowed_keys(config, {"platform", "technology", "artifacts"}, "config")
        platform = self._get_platform(config)
        technology = self._get_technology(config)
        artifacts = self._get_artifacts(config)
        if platform["os"] != "linux":
            raise NotImplementedError("Technology not supported!")
        if technology["type"] != "python":
            raise NotImplementedError("Technology not supported!")

        self._builder.reset()
        self._builder.comment("Generated Dockerfile. Do not edit by hand.")

        base_image = self._select_base_image(platform, technology, {})
        self._builder.from_(base_image)

        self._emit_linux_zip_unpack(artifacts)
        self._emit_python_setup(platform, technology)

        return self._builder.build()

    def _get_platform(self, config):
        platform = config.get("platform")
        if not isinstance(platform, dict):
            raise ValueError("platform is required and must be a dict")
        self._assert_allowed_keys(platform, {"os", "arch"}, "platform")
        os_name = platform.get("os")
        if not isinstance(os_name, str) or not os_name.strip():
            raise ValueError("platform.os must be a non-empty string")
        arch = platform.get("arch")
        if arch is None:
            raise ValueError("platform.arch is required")
        arch = self._ensure_string(arch, "platform.arch")
        return {"os": os_name, "arch": arch}

    def _get_technology(self, config):
        technology = config.get("technology")
        if not isinstance(technology, dict):
            raise ValueError("technology is required and must be a dict")
        self._assert_allowed_keys(technology, {"type", "python", "java", "dotnet", "native"}, "technology")
        tech_type = technology.get("type")
        if not isinstance(tech_type, str) or not tech_type.strip():
            raise ValueError("technology.type must be a non-empty string")
        data = {"type": tech_type}
        data.update(technology)
        if tech_type == "python":
            python_cfg = technology.get("python") or {}
            if not isinstance(python_cfg, dict):
                raise ValueError("technology.python must be a dict")
            self._assert_allowed_keys(
                python_cfg, {"version", "packages"}, "technology.python"
            )
            if "version" not in python_cfg:
                raise ValueError("technology.python.version is required")
            data["python"] = python_cfg
        else:
            if "python" in technology:
                raise ValueError("technology.python is not supported for this type")
        return data

    def _get_artifacts(self, config):
        artifacts = config.get("artifacts")
        if not isinstance(artifacts, dict):
            raise ValueError("artifacts is required and must be a dict")
        self._assert_allowed_keys(artifacts, {"zip"}, "artifacts")

        zip_cfg = artifacts.get("zip")
        if not isinstance(zip_cfg, dict):
            raise ValueError("artifacts.zip is required and must be a dict")
        if "destination" in zip_cfg:
            raise ValueError(
                "artifacts.zip.destination is not supported; destination is fixed to /opt/simulator"
            )
        self._assert_allowed_keys(zip_cfg, {"path", "strip_root"}, "artifacts.zip")

        path = self._ensure_string(zip_cfg.get("path"), "artifacts.zip.path")
        strip_root = zip_cfg.get("strip_root", False)
        if not isinstance(strip_root, bool):
            raise ValueError("artifacts.zip.strip_root must be a boolean")

        return {"zip": {"path": path, "strip_root": strip_root}}

    def _select_base_image(self, platform, technology, build):
        override = build.get("base_image")
        if override is not None:
            return self._ensure_string(override, "build.base_image")

        os_name = platform["os"]
        tech_type = technology["type"]

        if os_name == "linux" and tech_type == "python":
            python_cfg = technology.get("python", {})
            version = python_cfg.get("version") or "3.11"
            version = self._ensure_string(version, "technology.python.version")
            suffix = self._python_version_to_suffix(version)
            return f"{self._base_images.python_prefix}-{suffix}"

        raise NotImplementedError("Technology not supported!")

    def _python_version_to_suffix(self, version: str) -> str:
        text = self._ensure_string(version, "technology.python.version")
        parts = text.split(".")
        if len(parts) != 2:
            raise ValueError(
                "technology.python.version must be in 'major.minor' format"
            )
        try:
            major = int(parts[0])
            minor = int(parts[1])
        except ValueError as exc:
            raise ValueError(
                "technology.python.version must be in 'major.minor' format"
            ) from exc
        if major < 0 or minor < 0:
            raise ValueError(
                "technology.python.version must be in 'major.minor' format"
            )
        return f"{major}{minor:02d}"

    def _emit_python_setup(self, platform, technology):
        python_cfg = technology.get("python", {})
        venv_path = "/opt/simulator/.venv"
        python_cmd = f"{venv_path}/bin/python"

        packages = python_cfg.get("packages")
        if packages:
            packages = self._apply_pytorch_workaround(packages, python_cmd)

            if packages:
                pkg_list = self._normalize_packages(packages)
                pkg_text = " ".join(pkg_list)
                self._builder.run(f"{python_cmd} -m pip install --no-cache-dir {pkg_text}")

        technology["_venv_path"] = f"{venv_path}/bin"
        return None

    def _apply_pytorch_workaround(self, packages, python_cmd):
        """
        Temporary workaround for PyTorch packages.

        Installs torch/torchvision/torchaudio separately using the official
        PyTorch CPU wheel index, then returns the remaining packages so they
        can be installed via the normal path.

        Hardcoded on purpose for now, so it is easy to find and remove later.
        """
        if not isinstance(packages, list):
            raise ValueError("technology.python.packages must be a list")

        pytorch_names = {"torch", "torchvision", "torchaudio"}

        pytorch_packages = []
        other_packages = []

        for item in packages:
            if not isinstance(item, dict):
                raise ValueError("technology.python.packages items must be dicts")

            name = self._ensure_string(item.get("name"), "technology.python.packages.name")
            if name in pytorch_names:
                pytorch_packages.append(item)
            else:
                other_packages.append(item)

        if not pytorch_packages:
            return packages

        ordered_names = ["torch", "torchvision", "torchaudio"]
        by_name = {
            self._ensure_string(item.get("name"), "technology.python.packages.name"): item
            for item in pytorch_packages
        }

        reqs = []
        for name in ordered_names:
            item = by_name.get(name)
            if item is None:
                continue

            version = item.get("version")
            if version is None:
                reqs.append(name)
                continue

            version_text = self._ensure_string(
                version, "technology.python.packages.version"
            )

            # Temporary normalization:
            # users may provide versions like "2.6.0+cpu", but with the current
            # official CPU index flow we want plain versions like "2.6.0".
            normalized_version = version_text.split("+", 1)[0]

            reqs.append(f"{name}=={normalized_version}")

        if reqs:
            req_text = " ".join(reqs)
            self._builder.run(
                f"{python_cmd} -m pip install --no-cache-dir "
                f"--index-url https://download.pytorch.org/whl/cpu "
                f"{req_text}"
            )

        return other_packages

    def _emit_linux_zip_unpack(self, artifacts):
        zip_cfg = artifacts["zip"]
        zip_path = zip_cfg["path"]
        strip_root = zip_cfg["strip_root"]

        self._builder.run(
            "apt-get update && apt-get install -y --no-install-recommends unzip ca-certificates && rm -rf /var/lib/apt/lists/*"
        )
        self._builder.copy(zip_path, "/tmp/user_sim.zip")
        self._builder.run(
            "if unzip -Z1 /tmp/user_sim.zip | grep -E '^(\\./)?\\.venv/'; then "
            'echo "artifact zip must not contain /opt/simulator/.venv content"; '
            "exit 1; "
            "fi"
        )
        self._builder.run(
            'mkdir -p "/opt/simulator" "/tmp/user_sim_extract" '
            '&& unzip -q "/tmp/user_sim.zip" -d "/tmp/user_sim_extract" '
            '&& rm "/tmp/user_sim.zip" '
            '&& count="$(find "/tmp/user_sim_extract" -mindepth 1 -maxdepth 1 -print | wc -l)" '
            '&& top="$(find "/tmp/user_sim_extract" -mindepth 1 -maxdepth 1 -print -quit)" '
            '&& if [ "$count" -eq 1 ] && [ -d "$top" ]; then '
            'cp -a "$top/." "/opt/simulator/"; '
            'else '
            'cp -a "/tmp/user_sim_extract/." "/opt/simulator/"; '
            'fi '
            '&& rm -rf "/tmp/user_sim_extract"'
        )

    def _normalize_packages(self, packages):
        if not isinstance(packages, list):
            raise ValueError("technology.python.packages must be a list")
        result = []
        for item in packages:
            if not isinstance(item, dict):
                raise ValueError("technology.python.packages items must be dicts")
            name = self._ensure_string(item.get("name"), "technology.python.packages.name")
            version = item.get("version")
            if version is None:
                result.append(name)
            else:
                version_text = self._ensure_string(
                    version, "technology.python.packages.version"
                )
                result.append(f"{name}=={version_text}")
        if not result:
            raise ValueError("technology.python.packages must not be empty")
        return result

    def _ensure_string(self, value, name):
        if not isinstance(value, str):
            raise ValueError(f"{name} must be a non-empty string")
        text = value.strip()
        if not text:
            raise ValueError(f"{name} must be a non-empty string")
        return text

    def _ensure_list(self, value, name):
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"{name} must be a list of non-empty strings")
        items = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError(f"{name} items must be strings")
            text = item.strip()
            if not text:
                raise ValueError(f"{name} items must be non-empty strings")
            items.append(text)
        if not items:
            raise ValueError(f"{name} must not be empty")
        return items

    def _sorted_keys(self, mapping, name):
        if not isinstance(mapping, dict):
            raise ValueError(f"{name} must be a dict")
        keys = []
        for key in mapping.keys():
            if not isinstance(key, str) or not key.strip():
                raise ValueError(f"{name} keys must be non-empty strings")
            keys.append(key)
        return sorted(keys)

    def _assert_allowed_keys(self, obj: dict, allowed: set[str], path: str) -> None:
        for key in obj.keys():
            if key not in allowed:
                raise ValueError(f"Unknown field: {path}.{key}")
