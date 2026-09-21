"""GitHub Releases checking and the frozen-app update helper.

The running application never overwrites its own executable.  It copies the
frozen executable to a temporary directory, starts that copy as an updater,
and then exits.  The updater downloads and verifies the ZIP, swaps only the
program directory, and starts the new executable.  The user-selected data
directory is outside that directory and is therefore left untouched.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

UPDATE_REPOSITORY = 'Oujiang-77/yiwu-counter'
UPDATE_API_URL = f'https://api.github.com/repos/{UPDATE_REPOSITORY}/releases/latest'
PACKAGE_SUFFIX = '-Windows-x64.zip'
VERSION_PATTERN = re.compile(r'^v?(\d+(?:\.\d+){0,3})$')


def version_key(value: str):
    match = VERSION_PATTERN.fullmatch((value or '').strip())
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split('.'))


def is_newer(remote: str, current: str) -> bool:
    remote_key, current_key = version_key(remote), version_key(current)
    if remote_key is None or current_key is None:
        return False
    width = max(len(remote_key), len(current_key))
    return remote_key + (0,) * (width - len(remote_key)) > current_key + (0,) * (width - len(current_key))


def parse_release(release: dict, current_version: str) -> dict:
    tag = str(release.get('tag_name') or '')
    latest_version = tag[1:] if tag.startswith('v') else tag
    package = next((asset for asset in release.get('assets', []) if str(asset.get('name') or '').endswith(PACKAGE_SUFFIX)), None)
    if not version_key(latest_version):
        return {'status': 'invalid-release', 'message': '线上发布版本号格式无效'}
    if not package:
        return {'status': 'incomplete-release', 'message': '线上发布缺少 Windows 安装包'}
    package_name = str(package.get('name') or '')
    checksum_names = (package_name + '.sha256.txt', package_name.removesuffix('.zip') + '.sha256.txt')
    checksum = next((asset for asset in release.get('assets', []) if str(asset.get('name') or '') in checksum_names), None)
    return {
        'status': 'ok',
        'currentVersion': current_version,
        'latestVersion': latest_version,
        'updateAvailable': is_newer(latest_version, current_version),
        'releaseName': str(release.get('name') or f'v{latest_version}'),
        'notes': str(release.get('body') or '').strip(),
        'publishedAt': release.get('published_at'),
        'releaseUrl': str(release.get('html_url') or f'https://github.com/{UPDATE_REPOSITORY}/releases/tag/{tag}'),
        'package': {
            'name': package_name,
            'url': str(package.get('browser_download_url') or ''),
            'bytes': int(package.get('size') or 0),
            'checksumUrl': str(checksum.get('browser_download_url') or '') if checksum else '',
        },
    }


def check_for_update(current_version: str, timeout: int = 8) -> dict:
    request = urllib.request.Request(
        UPDATE_API_URL,
        headers={'Accept': 'application/vnd.github+json', 'User-Agent': f'HuoYouShu/{current_version}'},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            release = json.loads(response.read().decode('utf8'))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {'status': 'no-release', 'currentVersion': current_version, 'message': '暂未发布在线更新版本'}
        return {'status': 'unavailable', 'currentVersion': current_version, 'message': '暂时无法连接更新服务'}
    except (OSError, ValueError, json.JSONDecodeError):
        return {'status': 'unavailable', 'currentVersion': current_version, 'message': '暂时无法连接更新服务'}
    if not isinstance(release, dict):
        return {'status': 'invalid-release', 'currentVersion': current_version, 'message': '线上发布信息格式无效'}
    return parse_release(release, current_version)


def _windows_process_running(pid: int) -> bool:
    """Return whether a Windows process is still alive without a dependency."""
    if pid <= 0:
        return False
    if os.name != 'nt':
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _wait_for_process_exit(pid: int, timeout: float = 120.0) -> None:
    deadline = time.monotonic() + timeout
    while _windows_process_running(pid) and time.monotonic() < deadline:
        time.sleep(0.25)
    if _windows_process_running(pid):
        raise RuntimeError('旧版本程序没有在规定时间内退出')


def _download(url: str, destination: Path) -> None:
    if not url:
        raise RuntimeError('更新包地址为空')
    request = urllib.request.Request(url, headers={'User-Agent': 'HuoYouShu updater'})
    with urllib.request.urlopen(request, timeout=60) as response, destination.open('wb') as output:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)


def _read_checksum(url: str, package: Path) -> str:
    if not url:
        raise RuntimeError('线上发布缺少 SHA256 校验文件')
    request = urllib.request.Request(url, headers={'User-Agent': 'HuoYouShu updater'})
    with urllib.request.urlopen(request, timeout=30) as response:
        text = response.read().decode('utf8', errors='replace')
    match = re.search(r'\b([0-9a-fA-F]{64})\b', text)
    if not match:
        raise RuntimeError('SHA256 校验文件格式无效')
    actual = hashlib.sha256(package.read_bytes()).hexdigest()
    expected = match.group(1).lower()
    if actual != expected:
        raise RuntimeError('更新包校验失败，未替换当前程序')
    return actual


def _safe_extract(zip_path: Path, destination: Path) -> Path:
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            name = member.filename.replace('\\', '/')
            target = (destination / name).resolve()
            if target != destination.resolve() and destination.resolve() not in target.parents:
                raise RuntimeError('更新包包含不安全路径')
        archive.extractall(destination)
    candidates = [p for p in destination.iterdir() if p.is_dir()]
    for candidate in candidates:
        if any(p.suffix.lower() == '.exe' for p in candidate.iterdir() if p.is_file()):
            return candidate
    raise RuntimeError('更新包中没有找到程序目录')


def _restart_executable(program_dir: Path) -> Path:
    executables = [p for p in program_dir.glob('*.exe') if p.is_file()]
    if not executables:
        raise RuntimeError('更新后的程序目录中没有可启动文件')
    preferred = program_dir / '档口开单系统.exe'
    return preferred if preferred.is_file() else executables[0]


def _prompt_restart() -> bool:
    """Ask the desktop user whether the freshly installed version may start."""
    if os.name != 'nt':
        return True
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    # MB_OKCANCEL | MB_ICONINFORMATION
    result = user32.MessageBoxW(0, '更新已完成，点击“确定”重启档口开单系统。', '档口开单系统', 0x31)
    return result != 2


def run_update_helper(*, package_url: str, checksum_url: str, target_dir: str, pid: int) -> None:
    """Download, verify, replace and restart a packaged onedir application."""
    target = Path(target_dir).resolve()
    if not target.is_dir():
        raise RuntimeError('当前程序目录不存在')
    work = Path(tempfile.mkdtemp(prefix='huoyoushu-update-'))
    package = work / 'update.zip'
    extracted = work / 'extracted'
    old_dir = target.with_name(target.name + '.update-old-' + str(os.getpid()))
    try:
        _download(package_url, package)
        _read_checksum(checksum_url, package)
        extracted.mkdir()
        staged = _safe_extract(package, extracted)
        _wait_for_process_exit(pid)
        try:
            os.replace(target, old_dir)
            os.replace(staged, target)
        except Exception:
            if not target.exists() and old_dir.exists():
                os.replace(old_dir, target)
            raise
        executable = _restart_executable(target)
        if not _prompt_restart():
            return
        flags = getattr(subprocess, 'DETACHED_PROCESS', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
        subprocess.Popen([str(executable), '--updated'], cwd=str(target), close_fds=True, creationflags=flags)
        try:
            shutil.rmtree(old_dir)
        except OSError:
            pass
    finally:
        # The helper executable itself is inside this temporary directory on
        # Windows, so a detached cleanup command removes it after exit.
        if os.name == 'nt':
            command = f'ping 127.0.0.1 -n 3 >nul & rmdir /s /q "{work}"'
            subprocess.Popen(['cmd.exe', '/d', '/c', command], creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        else:
            shutil.rmtree(work, ignore_errors=True)
