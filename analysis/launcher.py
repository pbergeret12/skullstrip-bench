"""
Everything that depends on the container engine (Docker or Apptainer) lives
here, so the processing code never needs to know which one is running.

Images are never downloaded: they come from a containers folder holding only
Docker archives (`<name>.tar`, from `docker save`) and/or `<name>.sif` files.
"""
import os
import shlex
import shutil
import subprocess
from pathlib import Path

ENGINES = ("apptainer", "docker")  # auto-detection order
DOCKER_KILL_TIMEOUT_S = 60
# Environment variables that cap a tool's threads, whatever library it uses
# (ITK for ANTs, OpenMP for most others). Without them a tool may grab every
# core of a shared cluster node.
THREAD_VARIABLES = ("ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS", "OMP_NUM_THREADS")


class RunTimeout(Exception):
    """A container ran longer than its tool's `timeout_min`."""


def detect_engine(forced=None):
    """
    Pick the engine: `forced` if given, else Apptainer if available, else Docker.

    Returns `(engine, problem)`: `engine` is None when nothing usable was found.
    """
    if forced and forced not in ENGINES:
        return None, f"unknown engine '{forced}' (choose from {', '.join(ENGINES)})"
    for engine in [forced] if forced else ENGINES:
        if engine_is_ready(engine):
            return engine, None
    wanted = forced or " or ".join(ENGINES)
    return None, f"{wanted} not found (or the Docker daemon is not running)"


def engine_is_ready(engine):
    """Whether the engine's command exists (and, for Docker, its daemon answers)."""
    if not shutil.which(engine):
        return False
    if engine == "docker":
        return _quiet_run(["docker", "info"]) == 0
    return True


def list_image_files(containers_dir):
    """Base names of the images in the containers folder (`synthstrip_1.8`, ...)."""
    return sorted({path.stem for path in Path(containers_dir).glob("*.tar")}
                  | {path.stem for path in Path(containers_dir).glob("*.sif")})


def image_status(engine, tool, containers_dir, require_sif=False):
    """
    Whether the tool's image can be used, without changing anything.

    Returns `(ready, message)`. An image that still has to be loaded (Docker)
    or built (Apptainer) from its `.tar` counts as ready: that happens on the
    first run — unless `require_sif`, for cluster jobs, where every array task
    would otherwise try to build the same `.sif` at once.
    """
    tar_file = Path(containers_dir) / f"{tool['container']}.tar"
    sif_file = Path(containers_dir) / f"{tool['container']}.sif"
    if engine == "docker":
        if _quiet_run(["docker", "image", "inspect", tool["image"]]) == 0:
            return True, f"{tool['image']} already loaded"
        if tar_file.is_file():
            return True, f"will be loaded from {tar_file.name}"
    if engine == "apptainer":
        if sif_file.is_file():
            return True, f"{sif_file.name} found"
        if tar_file.is_file() and require_sif:
            return False, (f"{sif_file.name} not built yet: run `invoke prepare-images` "
                           "on a login node first")
        if tar_file.is_file():
            return True, f"{sif_file.name} will be built from {tar_file.name}"
    return False, f"no {tar_file.name} or {sif_file.name} in {containers_dir}"


def prepare_image(engine, tool, containers_dir):
    """
    Make the tool's image runnable and return what to pass to the engine.

    Docker: `docker load` the `.tar` if the image is not loaded yet; returns
    the image reference. Apptainer: build `<name>.sif` from the `.tar` once,
    next to it, and keep it; returns the `.sif` path.
    """
    tar_file = Path(containers_dir) / f"{tool['container']}.tar"
    if engine == "docker":
        if _quiet_run(["docker", "image", "inspect", tool["image"]]) != 0:
            print(f"    loading {tar_file.name} into Docker (once)...")
            subprocess.run(["docker", "load", "-i", str(tar_file)], check=True)
        return tool["image"]

    sif_file = Path(containers_dir) / f"{tool['container']}.sif"
    if not sif_file.is_file():
        print(f"    building {sif_file.name} from {tar_file.name} (once)...")
        subprocess.run(["apptainer", "build", str(sif_file),
                        f"docker-archive://{tar_file}"], check=True)
    return str(sif_file)


def container_command(engine, image, mounts, command, name="skullstrip-bench", threads=1):
    """
    The full engine command line that runs `command` inside `image`.

    `mounts` is a list of `(host_path, container_path, read_only)`. `name`
    labels the Docker container, so it can be stopped on timeout. `threads`
    caps the tool's threads through THREAD_VARIABLES.
    """
    if engine == "docker":
        options = ["docker", "run", "--rm", "--name", name, "--platform", "linux/amd64",
                   "--entrypoint", ""]
        mount_flag, env_flag = "-v", "-e"
    else:
        options = ["apptainer", "exec", "--compat"]
        mount_flag, env_flag = "--bind", "--env"
    for host_path, container_path, read_only in mounts:
        suffix = ":ro" if read_only else ""
        options += [mount_flag, f"{Path(host_path).resolve()}:{container_path}{suffix}"]
    for variable in THREAD_VARIABLES:
        options += [env_flag, f"{variable}={threads}"]
    return options + [image] + command


def run_container(engine, image, mounts, command, log_file, err_file, timeout_min=None,
                  threads=1):
    """
    Run `command` in the container and return its exit code. Its standard
    output goes to `log_file` (after a first line with the full command), its
    errors to `err_file`. Past `timeout_min` minutes (if set), stop it and
    raise RunTimeout.
    """
    name = f"skullstrip-bench-{os.getpid()}-{Path(log_file).stem}"
    full_command = container_command(engine, image, mounts, command, name, threads)
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, "w") as log, open(err_file, "w") as err:
        log.write(f"# {shlex.join(full_command)}\n")
        log.flush()
        try:
            return subprocess.run(full_command, stdout=log, stderr=err,
                                  timeout=timeout_min * 60 if timeout_min else None).returncode
        except subprocess.TimeoutExpired:
            # Killing `docker run` leaves the container running in the VM: stop
            # it by name. An Apptainer container dies with its process.
            if engine == "docker":
                _stop_docker_container(name)
            raise RunTimeout(f"timed out after {timeout_min} min (timeout_min in the tool's YAML)")


def _stop_docker_container(name):
    """Kill a Docker container, without hanging if the Docker VM is unresponsive."""
    try:
        subprocess.run(["docker", "kill", name], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=DOCKER_KILL_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        pass


def _quiet_run(command):
    """Run a command, discard its output, return its exit code."""
    return subprocess.run(command, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode
