import pathlib
import subprocess
import tempfile
from typing import Tuple

from langchain_core.tools import tool

PROJECT_ROOT = pathlib.Path.cwd() / "generated_project"


def set_project_root(path: str) -> None:
    """Point all file tools at a new project root (e.g. a fresh temp dir per run)."""
    global PROJECT_ROOT
    PROJECT_ROOT = pathlib.Path(path)
    PROJECT_ROOT.mkdir(parents=True, exist_ok=True)


def safe_path_for_project(path: str) -> pathlib.Path:

    path = path.replace("\\", "/")
    p = (PROJECT_ROOT / path).resolve()
    if PROJECT_ROOT.resolve() not in p.parents and PROJECT_ROOT.resolve() != p.parent and PROJECT_ROOT.resolve() != p:
        raise ValueError("Attempt to write outside project root")
    return p


def collect_generated_files() -> dict:
    files = {}
    if not PROJECT_ROOT.exists():
        return files
    for f in PROJECT_ROOT.glob("**/*"):
        if f.is_file():
            rel = f.relative_to(PROJECT_ROOT).as_posix()
            try:
                files[rel] = f.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                # skip binary files (images, etc.) for the code/zip preview list
                files[rel] = None
    return files


@tool
def write_file(path: str, content: str) -> str:
    """Writes content to a file at the specified path within the project root."""
    p = safe_path_for_project(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    return f"WROTE:{p}"


@tool
def read_file(path: str) -> str:
    """Reads content from a file at the specified path within the project root."""
    p = safe_path_for_project(path)
    if not p.exists():
        return ""
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


@tool
def get_current_directory() -> str:
    """Returns the current working directory."""
    return str(PROJECT_ROOT)


@tool
def list_files(directory: str = ".") -> str:
    """Lists all files in the specified directory within the project root."""
    p = safe_path_for_project(directory)
    if not p.is_dir():
        return f"ERROR: {p} is not a directory"
    files = [f.relative_to(PROJECT_ROOT).as_posix() for f in p.glob("**/*") if f.is_file()]
    return "\n".join(files) if files else "No files found."

@tool
def list_file(directory: str = ".") -> str:
    """Alias for list_files. Lists all files in the specified directory within the project root."""
    return list_files.func(directory)

@tool
def run_cmd(cmd: str, cwd: str = None, timeout: int = 30) -> Tuple[int, str, str]:
    """Runs a shell command in the specified directory and returns the result."""
    cwd_dir = safe_path_for_project(cwd) if cwd else PROJECT_ROOT
    res = subprocess.run(cmd, shell=True, cwd=str(cwd_dir), capture_output=True, text=True, timeout=timeout)
    return res.returncode, res.stdout, res.stderr


def init_project_root(path: str = None) -> str:
    """Initialize a project root. If no path is given, create a fresh temp
    directory for this run so nothing is left behind on disk permanently."""
    if path is None:
        path = tempfile.mkdtemp(prefix="coder_agent_")
    set_project_root(path)
    return str(PROJECT_ROOT)