"""为 Electron Windows 打包准备干净的后端代码与独立 Python 运行环境。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

BACKEND_SKIP_TOP_DIRS = {"Data", "Tests", ".venv", ".pytest_cache", ".audit-tmp"}
BACKEND_SKIP_DIR_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".git"}
BACKEND_SKIP_FILES = {"RequirementsDev.txt", ".DS_Store", "Thumbs.db"}
BACKEND_SKIP_SUFFIXES = {".pyc", ".pyo", ".log", ".db", ".db-shm", ".db-wal"}

STDLIB_SKIP_DIRS = {"site-packages", "__pycache__", "test", "tests", "idlelib", "tkinter", "turtledemo", "ensurepip", "venv"}
SITE_PKG_DEV_DIRS = {"test", "tests", "demos", "doc", "docs", "include", "scripts"}

SITECUSTOMIZE_CODE = r'''"""固定打包版 Python 的 COM 生成缓存路径，确保运行时永不写入安装目录且不提前初始化 COM。"""

from __future__ import annotations

import importlib
import importlib.machinery
import importlib.util
import os
import sys
import tempfile
from pathlib import Path


def _ensure_cache_pkg(fullname: str, cache_dir: Path) -> Path | None:
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        init_file = cache_dir / "__init__.py"
        if not init_file.exists():
            init_file.write_text(f"# {fullname} cache\n", encoding="utf-8")
        return init_file
    except OSError:
        return None


class _Win32ComLoader:
    def __init__(self, inner, gen_dir: Path) -> None:  # type: ignore[no-untyped-def]
        self._inner = inner
        self._gen_dir = gen_dir

    def create_module(self, spec):  # type: ignore[no-untyped-def]
        return self._inner.create_module(spec)

    def exec_module(self, module) -> None:  # type: ignore[no-untyped-def]
        self._inner.exec_module(module)
        init_file = _ensure_cache_pkg("win32com.gen_py", self._gen_dir)
        if init_file is None:
            return
        # 无论宿主机注册表是否写入 GenPath，均在 win32com 加载后强制把 __gen_path__ 固定到用户可写缓存目录。
        module.__gen_path__ = str(self._gen_dir)
        gen_py = sys.modules.get("win32com.gen_py")
        if gen_py is None:
            gen_py = importlib.import_module("win32com.gen_py")
        else:
            gen_py.__path__ = [str(self._gen_dir)]
            gen_py.__file__ = str(init_file)
        module.gen_py = gen_py

    def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
        return getattr(self._inner, name)


class _ComCacheFinder:
    def __init__(self, targets: dict[str, Path]) -> None:
        self._targets = targets
        self._wrapping_win32com = False

    def find_spec(self, fullname: str, path=None, target=None):  # type: ignore[no-untyped-def]
        cache_dir = self._targets.get(fullname)
        if cache_dir is not None:
            init_file = _ensure_cache_pkg(fullname, cache_dir)
            if init_file is None:
                return None
            return importlib.util.spec_from_file_location(
                fullname,
                str(init_file),
                submodule_search_locations=[str(cache_dir)],
            )
        if fullname == "win32com" and not self._wrapping_win32com:
            self._wrapping_win32com = True
            try:
                spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
            finally:
                self._wrapping_win32com = False
            if spec is not None and spec.loader is not None:
                spec.loader = _Win32ComLoader(spec.loader, self._targets["win32com.gen_py"])
            return spec
        return None


def _configure_com_caches() -> None:
    base = Path(os.environ.get("KGDASH_CACHE_DIR") or (Path(tempfile.gettempdir()) / "KuGouDashboardCache"))
    targets = {
        "comtypes.gen": base / "comtypes",
        "win32com.gen_py": base / "win32com",
    }
    sys.meta_path.insert(0, _ComCacheFinder(targets))


_configure_com_caches()
'''


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _remove_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def _should_skip_backend_dir(rel_parts: tuple[str, ...], name: str) -> bool:
    if not rel_parts and (name in BACKEND_SKIP_TOP_DIRS or name.startswith("tmp")):
        return True
    return name in BACKEND_SKIP_DIR_NAMES


def stage_backend(backend_src: Path, backend_dest: Path) -> None:
    if not (backend_src / "Main.py").is_file():
        raise FileNotFoundError(f"未找到后端入口: {backend_src / 'Main.py'}")
    _remove_tree(backend_dest)
    backend_dest.mkdir(parents=True, exist_ok=True)

    for root, dirs, files in os.walk(backend_src):
        root_path = Path(root)
        rel = root_path.relative_to(backend_src)
        rel_parts = () if rel == Path(".") else rel.parts
        dirs[:] = sorted(d for d in dirs if not _should_skip_backend_dir(rel_parts, d))

        target_dir = backend_dest / rel
        target_dir.mkdir(parents=True, exist_ok=True)
        for filename in sorted(files):
            if filename in BACKEND_SKIP_FILES:
                continue
            src_file = root_path / filename
            if src_file.suffix.lower() in BACKEND_SKIP_SUFFIXES:
                continue
            shutil.copy2(src_file, target_dir / filename)

    _verify_clean_backend(backend_dest)


def _verify_clean_backend(backend_dest: Path) -> None:
    for bad in ("Data", "Tests", ".venv", "RequirementsDev.txt"):
        if (backend_dest / bad).exists():
            raise RuntimeError(f"打包后端目录残留非运行时文件: {bad}")
    for item in backend_dest.rglob("*"):
        if item.name == "__pycache__" or item.suffix.lower() in BACKEND_SKIP_SUFFIXES:
            raise RuntimeError(f"打包后端目录残留缓存或临时文件: {item}")


def _keep_dll(name: str, major: int, minor: int) -> bool:
    lower = name.lower()
    if not (lower.endswith(".pyd") or lower.endswith(".dll")):
        return False
    if lower.endswith(("_d.pyd", "_d.dll")):
        return False
    ft_tag = f"{major}{minor}t"
    if ft_tag in lower or f"cp{ft_tag}-" in lower:
        return False
    if lower.startswith(("_test", "_tkinter", "tcl", "tk", "xxlimited")):
        return False
    return True


def _strip_runtime_residue(python_dest: Path) -> None:
    site_packages = python_dest / "Lib" / "site-packages"
    for extra_dir in (
        site_packages / "bin",
        site_packages / "pywinauto" / "tests",
        site_packages / "comtypes" / "gen",
        site_packages / "win32com" / "gen_py",
    ):
        shutil.rmtree(extra_dir, ignore_errors=True)
    for root, dirs, _files in os.walk(site_packages, topdown=True):
        kept: list[str] = []
        for dirname in dirs:
            if dirname.lower() in SITE_PKG_DEV_DIRS or dirname == "__pycache__":
                shutil.rmtree(Path(root) / dirname, ignore_errors=True)
            else:
                kept.append(dirname)
        dirs[:] = kept
    (python_dest / ".bundle-stamp.json").unlink(missing_ok=True)
    for cache_dir in list(python_dest.rglob("__pycache__")):
        if cache_dir.is_dir():
            shutil.rmtree(cache_dir, ignore_errors=True)
    for item in list(python_dest.rglob("*")):
        if item.is_file() and item.suffix.lower() in {".pyc", ".pyo", ".pdb"}:
            item.unlink(missing_ok=True)


def _verify_clean_python(python_dest: Path) -> None:
    site_packages = python_dest / "Lib" / "site-packages"
    for forbidden in (
        python_dest / ".bundle-stamp.json",
        site_packages / "pywinauto" / "tests",
        site_packages / "comtypes" / "gen",
        site_packages / "win32com" / "gen_py",
    ):
        if forbidden.exists():
            raise RuntimeError(f"打包 Python 目录残留非预期路径: {forbidden}")
    for item in site_packages.rglob("*"):
        if item.is_dir() and item.name.lower() in SITE_PKG_DEV_DIRS:
            raise RuntimeError(f"打包 site-packages 残留第三方开发目录: {item}")
    for item in python_dest.rglob("*"):
        if item.name == "__pycache__" or item.suffix.lower() in {".pyc", ".pyo", ".pdb"}:
            raise RuntimeError(f"打包 Python 目录残留缓存或调试文件: {item}")


def _has_complete_python_layout(python_dest: Path, major: int, minor: int) -> bool:
    required = [
        python_dest / "python.exe",
        python_dest / f"python{major}{minor}.dll",
        python_dest / "vcruntime140.dll",
        python_dest / "vcruntime140_1.dll",
        python_dest / "DLLs" / "_sqlite3.pyd",
        python_dest / "DLLs" / "sqlite3.dll",
        python_dest / "Lib" / "os.py",
        python_dest / "Lib" / "site-packages" / "sitecustomize.py",
        python_dest / "Lib" / "site-packages" / "fastapi",
        python_dest / "Lib" / "site-packages" / "uvicorn",
        python_dest / "Lib" / "site-packages" / "pywin32_system32",
        python_dest / "Lib" / "site-packages" / "pywinauto",
    ]
    return all(item.exists() for item in required)


def _collect_installed_packages(site_packages: Path) -> dict[str, str]:
    versions: dict[str, str] = {}
    for dist_info in sorted(site_packages.glob("*.dist-info")):
        metadata = dist_info / "METADATA"
        if not metadata.is_file():
            continue
        name = version = ""
        for line in metadata.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("Name: ") and not name:
                name = line[6:].strip()
            elif line.startswith("Version: ") and not version:
                version = line[9:].strip()
            if name and version:
                break
        if name:
            versions[name] = version
    return versions


def stage_python(
    requirements_txt: Path,
    python_dest: Path,
    *,
    clean: bool = False,
    pip_index_url: str | None = None,
) -> None:
    if sys.platform != "win32":
        raise RuntimeError("Windows 独立 Python 运行环境仅支持在 Windows 上构建")
    if struct.calcsize("P") != 8 or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise RuntimeError(f"仅支持 64 位 x64 Python 构建独立环境，当前为 {platform.machine()} ({struct.calcsize('P') * 8}-bit)")
    base_prefix = Path(sys.base_prefix).resolve()
    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 12):
        raise RuntimeError(f"需要 Python 3.12+，当前为 {major}.{minor}")

    # 构建标记放在 .bundle 根目录而非 python/ 内，避免把构建机绝对路径打进安装包。
    stamp_file = python_dest.parent / ".bundle-stamp.json"
    constraints_txt = requirements_txt.with_name("Constraints.txt")
    sitecustomize_sha256 = _text_sha256(SITECUSTOMIZE_CODE)
    expected_identity = {
        "arch": "amd64",
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "base_prefix_sha256": _text_sha256(str(base_prefix)),
        "requirements_sha256": _sha256(requirements_txt),
        # Requirements.txt 用 -c 引用 Constraints.txt：锁定的版本变了也要重建运行环境。
        "constraints_sha256": _sha256(constraints_txt) if constraints_txt.is_file() else None,
        "sitecustomize_sha256": sitecustomize_sha256,
    }

    if not clean and stamp_file.is_file():
        try:
            current = json.loads(stamp_file.read_text(encoding="utf-8"))
            if all(current.get(k) == v for k, v in expected_identity.items()) and _has_complete_python_layout(python_dest, major, minor):
                print("独立 Python 运行环境已是最新，跳过重建")
                return
        except Exception:
            pass

    _remove_tree(python_dest)
    python_dest.mkdir(parents=True, exist_ok=True)

    required_core = {
        "python.exe",
        f"python{major}{minor}.dll",
        "vcruntime140.dll",
        "vcruntime140_1.dll",
    }
    core_files = [
        "python.exe",
        "pythonw.exe",
        "python3.dll",
        f"python{major}{minor}.dll",
        "vcruntime140.dll",
        "vcruntime140_1.dll",
        "LICENSE.txt",
    ]
    for name in core_files:
        src = base_prefix / name
        if src.is_file():
            shutil.copy2(src, python_dest / name)
        elif name in required_core:
            raise FileNotFoundError(f"未在 Python 安装目录找到必需运行库/核心文件: {src}")

    dlls_src = base_prefix / "DLLs"
    dlls_dest = python_dest / "DLLs"
    dlls_dest.mkdir(parents=True, exist_ok=True)
    for item in sorted(dlls_src.iterdir()):
        if item.is_file() and _keep_dll(item.name, major, minor):
            shutil.copy2(item, dlls_dest / item.name)

    lib_src = base_prefix / "Lib"
    lib_dest = python_dest / "Lib"
    for root, dirs, files in os.walk(lib_src):
        root_path = Path(root)
        rel = root_path.relative_to(lib_src)
        is_top = rel == Path(".")
        dirs[:] = sorted(
            d
            for d in dirs
            if d != "__pycache__" and not (is_top and d in STDLIB_SKIP_DIRS)
        )
        target_dir = lib_dest / rel
        target_dir.mkdir(parents=True, exist_ok=True)
        for filename in sorted(files):
            src_file = root_path / filename
            if src_file.suffix.lower() in {".pyc", ".pyo"}:
                continue
            shutil.copy2(src_file, target_dir / filename)

    site_packages = lib_dest / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)

    pip_cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--no-compile",
        "--ignore-installed",
        "--no-warn-script-location",
        "-r",
        str(requirements_txt),
        "--target",
        str(site_packages),
    ]
    if pip_index_url:
        pip_cmd.extend(["-i", pip_index_url])

    subprocess.run(pip_cmd, check=True)
    (site_packages / "sitecustomize.py").write_text(SITECUSTOMIZE_CODE, encoding="utf-8")
    _strip_runtime_residue(python_dest)

    stamp_payload = {
        **expected_identity,
        "packages": _collect_installed_packages(site_packages),
    }
    stamp_file.write_text(json.dumps(stamp_payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _reserve_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def verify_isolated_runtime(python_dest: Path, backend_dest: Path, runner_script: Path) -> None:
    """在剥离宿主 PATH / PYTHONPATH / 用户 site-packages 的环境下执行全链路实测验证。"""

    python_exe = python_dest / "python.exe"
    if not python_exe.is_file():
        raise FileNotFoundError(f"未找到独立 Python 可执行文件: {python_exe}")
    if not runner_script.is_file():
        raise FileNotFoundError(f"未找到桌面启动脚本: {runner_script}")

    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    with tempfile.TemporaryDirectory(prefix="kgdash-bundle-verify-") as temp_root_str:
        temp_root = Path(temp_root_str)
        cache_dir = temp_root / "cache"
        db_path = temp_root / "Data" / "dashboard.db"
        frontend_dir = temp_root / "frontend"
        frontend_dir.mkdir(parents=True, exist_ok=True)
        (frontend_dir / "index.html").write_text("<html><body>desktop-verify</body></html>", encoding="utf-8")

        clean_env = {
            "SystemRoot": system_root,
            "WINDIR": system_root,
            "TEMP": str(temp_root),
            "TMP": str(temp_root),
            "PATH": f"{system_root}\\System32;{system_root}",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "KGDASH_CACHE_DIR": str(cache_dir),
        }

        probe = """
import pathlib, sys
prefix = pathlib.Path(sys.prefix).resolve()
expected = pathlib.Path(sys.argv[1]).resolve()
cache_root = pathlib.Path(sys.argv[2]).resolve()
if prefix != expected:
    raise SystemExit(f"unexpected sys.prefix={prefix}, expected={expected}")
import fastapi, uvicorn, pydantic, sqlite3, ssl, ctypes
import win32api, win32gui, win32ui, win32con, pythoncom
# 模拟宿主机注册表存在 GenPath，验证 _Win32ComLoader 仍强制将缓存锁定到 KGDASH_CACHE_DIR。
orig_reg_query = win32api.RegQueryValue
win32api.RegQueryValue = lambda key, subkey: r"C:\\FakeHostRegistryGenPath" if subkey == "GenPath" else orig_reg_query(key, subkey)
try:
    import win32com, win32com.client
finally:
    win32api.RegQueryValue = orig_reg_query
import comtypes, comtypes.client, pywinauto
import pywinauto.uia_defines
pywinauto.uia_defines.IUIA()
gen_dir = pathlib.Path(comtypes.client.gen_dir).resolve()
expected_comtypes = (cache_root / "comtypes").resolve()
if gen_dir != expected_comtypes:
    raise SystemExit(f"comtypes.client.gen_dir={gen_dir}, expected={expected_comtypes}")
win32_gen = pathlib.Path(win32com.__gen_path__).resolve()
expected_win32 = (cache_root / "win32com").resolve()
if win32_gen != expected_win32:
    raise SystemExit(f"win32com.__gen_path__={win32_gen}, expected={expected_win32}")
if pathlib.Path(win32com.gen_py.__path__[0]).resolve() != expected_win32:
    raise SystemExit(f"win32com.gen_py.__path__={win32com.gen_py.__path__}, expected={expected_win32}")
import Main
assert Main.create_app() is not None
print("RUNTIME_IMPORTS_AND_COM_CACHE_OK")
"""
        probe_result = subprocess.run(
            [str(python_exe), "-X", "utf8", "-s", "-c", probe, str(python_dest), str(cache_dir)],
            cwd=str(backend_dest),
            env=clean_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if probe_result.returncode != 0:
            raise RuntimeError(
                f"独立 Python 依赖与 COM 缓存自检失败 (exit={probe_result.returncode}):\n{probe_result.stdout}\n{probe_result.stderr}"
            )

        worker_proc = subprocess.run(
            [str(python_exe), "-X", "utf8", "-m", "KugouControl.Worker", "--serve"],
            cwd=str(backend_dest),
            env=clean_env,
            input="read\n",
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
        )
        if worker_proc.returncode != 0 or not worker_proc.stdout.strip():
            raise RuntimeError(
                f"KugouControl.Worker --serve 自检失败 (exit={worker_proc.returncode}):\n{worker_proc.stdout}\n{worker_proc.stderr}"
            )
        worker_payload = json.loads(worker_proc.stdout.strip().splitlines()[0])
        if "data" not in worker_payload or "connected" not in worker_payload["data"]:
            raise RuntimeError(f"KugouControl.Worker 返回格式异常: {worker_payload}")

        port = _reserve_loopback_port()
        runner_env = {
            **clean_env,
            "KGDASH_HOST": "127.0.0.1",
            "KGDASH_PORT": str(port),
            "KGDASH_BACKEND_DIR": str(backend_dest),
            "DB_PATH": str(db_path),
            "FRONTEND_DIST": str(frontend_dir),
            "KUGOU_SEARCH": "off",
        }
        server_proc = subprocess.Popen(
            [str(python_exe), "-X", "utf8", str(runner_script)],
            cwd=str(backend_dest),
            env=runner_env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
        )
        try:
            deadline = time.monotonic() + 20.0
            healthy = False
            while time.monotonic() < deadline:
                if server_proc.poll() is not None:
                    break
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as resp:
                        if resp.status == 200 and json.loads(resp.read().decode("utf-8")).get("status") == "ok":
                            healthy = True
                            break
                except Exception:
                    time.sleep(0.15)
            if not healthy:
                out = server_proc.communicate(timeout=3)[0] if server_proc.poll() is not None else ""
                raise RuntimeError(f"打包后端 HTTP 服务启动自检失败:\n{out}")

            for route, expect_code in (
                ("/", 200),
                ("/api/connection", 200),
                ("/api/songs", 200),
                ("/api/diagnostics", 200),
            ):
                with urllib.request.urlopen(f"http://127.0.0.1:{port}{route}", timeout=3) as resp:
                    if resp.status != expect_code:
                        raise RuntimeError(f"路由 {route} 返回异常状态码: {resp.status}")

            if server_proc.stdin:
                server_proc.stdin.write("shutdown\n")
                server_proc.stdin.flush()
                server_proc.stdin.close()
            stdout_log, _ = server_proc.communicate(timeout=10)
            if server_proc.returncode != 0:
                raise RuntimeError(f"打包后端优雅退出异常 (exit={server_proc.returncode}):\n{stdout_log}")
        finally:
            if server_proc.poll() is None:
                server_proc.kill()
                server_proc.wait(timeout=3)

        if not db_path.is_file() or db_path.stat().st_size == 0:
            raise RuntimeError(f"后端启动后未在可写目标位置创建 SQLite 数据库: {db_path}")

    _verify_clean_backend(backend_dest)
    _verify_clean_python(python_dest)
    print(f"RUNTIME_ISOLATION_OK {python_dest}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="准备 Electron Windows 打包环境")
    parser.add_argument("--clean", action="store_true", help="强制重建独立 Python 运行环境")
    parser.add_argument("--verify-only", action="store_true", help="仅校验当前 .bundle 目录")
    parser.add_argument("--index-url", default=None, help="可选自定义 pip 镜像源")
    args = parser.parse_args(argv)

    desktop_dir = Path(__file__).resolve().parents[1]
    repo_root = desktop_dir.parent
    bundle_dir = desktop_dir / ".bundle"
    backend_src = repo_root / "Backend"
    backend_dest = bundle_dir / "backend"
    python_dest = bundle_dir / "python"
    requirements_txt = backend_src / "Requirements.txt"
    runner_script = desktop_dir / "Resources" / "BackendRunner.py"

    if not args.verify_only:
        stage_backend(backend_src, backend_dest)
        stage_python(
            requirements_txt,
            python_dest,
            clean=args.clean,
            pip_index_url=args.index_url,
        )
    else:
        _verify_clean_backend(backend_dest)
        _verify_clean_python(python_dest)

    verify_isolated_runtime(python_dest, backend_dest, runner_script)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
