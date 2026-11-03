import json


class DockerfileBuilder:
    """Builds Dockerfile content line-by-line with basic validation."""

    def __init__(self):
        self._lines = []

    def reset(self):
        self._lines = []
        return self

    def build(self):
        return "\n".join(self._lines) + "\n"

    def include_blank_line(self):
        self._lines.append("")
        return self

    def raw(self, line):
        text = self._ensure_string(line, "raw line")
        self._lines.append(text)
        return self

    def comment(self, text):
        message = self._ensure_string(text, "comment")
        self._lines.append(f"# {message}")
        return self

    def from_(self, image, alias=None):
        image_text = self._ensure_string(image, "FROM image")
        if alias is None:
            line = f"FROM {image_text}"
        else:
            alias_text = self._ensure_string(alias, "FROM alias")
            line = f"FROM {image_text} AS {alias_text}"
        self._lines.append(line)
        return self

    def run(self, command, shell_form=True):
        self._lines.append(self._format_command("RUN", command, shell_form))
        return self

    def cmd(self, command, shell_form=True):
        self._lines.append(self._format_command("CMD", command, shell_form))
        return self

    def entrypoint(self, command, shell_form=True):
        self._lines.append(self._format_command("ENTRYPOINT", command, shell_form))
        return self

    def copy(self, src, dest, options=None, json_form=False):
        self._lines.append(
            self._format_copy_add("COPY", src, dest, options, json_form)
        )
        return self

    def add(self, src, dest, options=None, json_form=False):
        self._lines.append(self._format_copy_add("ADD", src, dest, options, json_form))
        return self

    def workdir(self, path):
        path_text = self._ensure_string(path, "WORKDIR path")
        self._lines.append(f"WORKDIR {path_text}")
        return self

    def env(self, key, value):
        key_text = self._ensure_string(key, "ENV key")
        value_text = self._ensure_string(value, "ENV value")
        formatted = self._format_key_value(key_text, value_text)
        self._lines.append(f"ENV {formatted}")
        return self

    def arg(self, name, default=None):
        name_text = self._ensure_string(name, "ARG name")
        if default is None:
            line = f"ARG {name_text}"
        else:
            default_text = self._ensure_string_or_int(default, "ARG default")
            formatted = self._format_key_value(name_text, default_text)
            line = f"ARG {formatted}"
        self._lines.append(line)
        return self

    def user(self, user):
        user_text = self._ensure_string(user, "USER")
        self._lines.append(f"USER {user_text}")
        return self

    def expose(self, ports):
        ports_text = self._format_str_or_list(ports, "EXPOSE ports")
        self._lines.append(f"EXPOSE {ports_text}")
        return self

    def volume(self, paths):
        path_items = self._ensure_list_or_string(paths, "VOLUME paths")
        self._lines.append(f"VOLUME {json.dumps(path_items)}")
        return self

    def label(self, key, value):
        key_text = self._ensure_string(key, "LABEL key")
        value_text = self._ensure_string(value, "LABEL value")
        formatted = self._format_key_value(key_text, value_text)
        self._lines.append(f"LABEL {formatted}")
        return self

    def shell(self, command):
        if isinstance(command, (list, tuple)):
            items = self._ensure_list(command, "SHELL command")
            line = f"SHELL {json.dumps(items)}"
        else:
            command_text = self._ensure_string(command, "SHELL command")
            line = f"SHELL {command_text}"
        self._lines.append(line)
        return self

    def stopsignal(self, signal):
        signal_text = self._ensure_string(signal, "STOPSIGNAL")
        self._lines.append(f"STOPSIGNAL {signal_text}")
        return self

    def healthcheck(
        self,
        command,
        interval=None,
        timeout=None,
        start_period=None,
        retries=None,
        none=False,
    ):
        if none:
            if command is not None or any(
                value is not None
                for value in (interval, timeout, start_period, retries)
            ):
                raise ValueError("HEALTHCHECK NONE does not accept extra arguments")
            self._lines.append("HEALTHCHECK NONE")
            return self

        if command is None:
            raise ValueError("HEALTHCHECK command is required when none is False")

        flags = []
        flags.extend(self._format_healthcheck_flag("interval", interval))
        flags.extend(self._format_healthcheck_flag("timeout", timeout))
        flags.extend(self._format_healthcheck_flag("start-period", start_period))
        flags.extend(self._format_healthcheck_retries(retries))

        if isinstance(command, (list, tuple)):
            cmd_items = self._ensure_list(command, "HEALTHCHECK command")
            cmd_text = json.dumps(cmd_items)
        else:
            cmd_text = self._ensure_string(command, "HEALTHCHECK command")

        tokens = ["HEALTHCHECK"] + flags + ["CMD", cmd_text]
        self._lines.append(" ".join(tokens))
        return self

    def onbuild(self, instruction_line):
        instruction_text = self._ensure_string(instruction_line, "ONBUILD instruction")
        self._lines.append(f"ONBUILD {instruction_text}")
        return self

    def maintainer(self, name):
        name_text = self._ensure_string(name, "MAINTAINER")
        self._lines.append(f"MAINTAINER {name_text}")
        return self

    def _format_command(self, instruction, command, shell_form):
        if shell_form:
            cmd_text = self._ensure_string(command, f"{instruction} command")
            return f"{instruction} {cmd_text}"
        if not isinstance(command, (list, tuple)):
            raise ValueError(
                f"{instruction} exec form requires a list of command arguments"
            )
        cmd_items = self._ensure_list(command, f"{instruction} command")
        return f"{instruction} {json.dumps(cmd_items)}"

    def _format_copy_add(self, instruction, src, dest, options, json_form):
        dest_text = self._ensure_string(dest, f"{instruction} dest")
        option_tokens = self._format_options(options)
        if json_form:
            src_items = self._ensure_list(src, f"{instruction} src")
            payload = src_items + [dest_text]
            tokens = [instruction] + option_tokens + [json.dumps(payload)]
            return " ".join(tokens)

        if isinstance(src, (list, tuple)):
            src_items = self._ensure_list(src, f"{instruction} src")
        else:
            src_items = [self._ensure_string(src, f"{instruction} src")]
        tokens = [instruction] + option_tokens + src_items + [dest_text]
        return " ".join(tokens)

    def _format_options(self, options):
        if options is None:
            return []
        if not isinstance(options, dict):
            raise ValueError("options must be a dict of flag values")
        tokens = []
        for key, value in options.items():
            key_text = self._ensure_string(key, "option key")
            value_text = self._ensure_string_or_int(value, f"option '{key_text}' value")
            tokens.append(f"--{key_text}={value_text}")
        return tokens

    def _format_key_value(self, key, value):
        value_text = self._quote_if_needed(value)
        return f"{key}={value_text}"

    def _format_str_or_list(self, value, name):
        if isinstance(value, (list, tuple)):
            items = self._ensure_list(value, name)
            return " ".join(items)
        return self._ensure_string(value, name)

    def _ensure_list_or_string(self, value, name):
        if isinstance(value, (list, tuple)):
            return self._ensure_list(value, name)
        return [self._ensure_string(value, name)]

    def _format_healthcheck_flag(self, name, value):
        if value is None:
            return []
        value_text = self._ensure_string_or_int(value, f"HEALTHCHECK {name}")
        return [f"--{name}={value_text}"]

    def _format_healthcheck_retries(self, retries):
        if retries is None:
            return []
        if isinstance(retries, bool):
            raise ValueError("HEALTHCHECK retries must be an integer")
        if isinstance(retries, int):
            if retries < 0:
                raise ValueError("HEALTHCHECK retries must be >= 0")
            return [f"--retries={retries}"]
        retries_text = self._ensure_string(retries, "HEALTHCHECK retries")
        return [f"--retries={retries_text}"]

    def _ensure_string_or_int(self, value, name):
        if isinstance(value, int):
            return str(value)
        return self._ensure_string(value, name)

    def _quote_if_needed(self, value):
        if any(char.isspace() for char in value):
            return '"' + value.replace('"', '\\"') + '"'
        return value

    def _ensure_string(self, value, name):
        if not isinstance(value, str):
            raise ValueError(f"{name} must be a string")
        text = value.strip()
        if not text:
            raise ValueError(f"{name} must be a non-empty string")
        return text

    def _ensure_list(self, value, name):
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"{name} must be a list of strings")
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
