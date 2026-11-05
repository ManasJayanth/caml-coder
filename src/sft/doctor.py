import platform
import shutil
import sys
import re
import urllib.request
import urllib.error
import urllib.parse
from .artifacts import Invalid, fields
from .process import run


def inspect(root, config):
    fields(config, ["schema_version", "minimum_disk_gib", "minimum_memory_gib", "require_docker", "require_apple_silicon", "endpoints"])
    if type(config["schema_version"]) is not int or config["schema_version"] != 1:
        raise Invalid("unsupported doctor config schema")
    for field in ("minimum_disk_gib", "minimum_memory_gib"):
        if type(config[field]) is not int or config[field] < 1:
            raise Invalid(f"{field} must be positive integer")
    for field in ("require_docker", "require_apple_silicon"):
        if type(config[field]) is not bool:
            raise Invalid(f"{field} must be boolean")
    if not isinstance(config["endpoints"], list):
        raise Invalid("endpoints must be an explicit list")
    for endpoint in config["endpoints"]:
        fields(endpoint, ["name", "url"])
        parsed = urllib.parse.urlsplit(endpoint["url"])
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.username or parsed.password:
            raise Invalid("doctor endpoints must be unauthenticated local HTTP URLs")
    checks = []

    def check(name, passed, observed):
        checks.append({"name": name, "status": "PASSED" if passed else "BLOCKED", "observed": observed})

    check("python", sys.version_info[:2] == (3, 12), sys.version)
    free = shutil.disk_usage(root).free / 1024 ** 3
    check("disk", free >= config["minimum_disk_gib"], {"free_gib": free, "required_gib": config["minimum_disk_gib"]})
    system = platform.system()
    check("platform", not config["require_apple_silicon"] or (system == "Darwin" and platform.machine() == "arm64"), platform.platform())
    if system == "Darwin":
        memory = run(["/usr/sbin/sysctl", "-n", "hw.memsize"])
        gib = int(memory["stdout"].strip()) / 1024**3 if memory["exit_code"] == 0 and memory["stdout"].strip().isdigit() else 0
        check("memory", gib >= config["minimum_memory_gib"], {"total_gib": gib, "required_gib": config["minimum_memory_gib"]})
    else:
        check("memory", False, "macOS memory probe unavailable")
    for binary in ("node", "npm", "git"):
        path = shutil.which(binary)
        result = run([path, "--version"]) if path else {"error": "missing executable"}
        match = re.search(r"(\d+)\.(\d+)\.(\d+)", result.get("stdout", ""))
        minimum = {"node":(22,19,0),"npm":(10,0,0),"git":(2,0,0)}[binary]
        compatible = bool(match) and tuple(map(int, match.groups())) >= minimum
        check(binary, bool(path) and result.get("exit_code") == 0 and compatible, result)
    if config["require_docker"]:
        path = shutil.which("docker")
        result = run([path, "version", "--format", "{{.Server.Version}}"], timeout=20) if path else {"error": "missing executable"}
        check("docker_daemon", bool(path) and result.get("exit_code") == 0 and bool(result.get("stdout", "").strip()), result)
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise Invalid("health endpoint redirects are forbidden")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    for endpoint in config["endpoints"]:
        try:
            with opener.open(endpoint["url"], timeout=3) as response:
                check(endpoint["name"], response.status == 200, {"url":endpoint["url"], "http_status":response.status})
        except (OSError, Invalid) as error:
            check(endpoint["name"], False, {"url":endpoint["url"], "error":str(error)})
    return {"status": "PASSED" if all(c["status"] == "PASSED" for c in checks) else "BLOCKED", "scope": "host-only; models, toolchain containers and local inference are not verified", "checks": checks, "effective_config": config}
