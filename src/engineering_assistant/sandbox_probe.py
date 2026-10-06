"""Actual sandbox diagnostic, independent of external advisory data.

A capability query is only preparation evidence. Qualification requires a
positive invocation and denied network/process/read/write probes on this host.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path

from .catalog import load_catalog
from .model import ProviderInvocation
from .provider_runtime import ProviderExecutor
from .validation import ValidationFailure


def _listener(stack: ExitStack, family: int) -> tuple:
    listener = stack.enter_context(socket.socket(family, socket.SOCK_STREAM))
    listener.settimeout(2)
    if family == socket.AF_INET6:
        listener.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
    listener.bind(("127.0.0.1" if family == socket.AF_INET else "::1", 0))
    listener.listen(4)
    endpoint = listener.getsockname()
    # Prove a real connection to this listener succeeds without confinement.
    with socket.socket(family, socket.SOCK_STREAM) as client:
        client.settimeout(2)
        client.connect(endpoint)
        accepted, _ = listener.accept()
        accepted.close()
    listener.setblocking(False)
    return listener, endpoint


def _invoke(catalog, bundle: Path, source: str, name: str, expected: set[str]) -> dict:
    (bundle / "scripts/search.py").write_text(source, encoding="utf-8")
    provider = catalog.providers["ui-ux-pro-max"]
    catalog.providers[provider.id] = replace(provider, source=replace(
        provider.source, integrity=ProviderExecutor._tree_integrity(bundle)))
    result = ProviderExecutor(catalog).invoke(ProviderInvocation(
        invocation_id="sandbox-probe-" + name, run_id="diagnostic", capability_id="frontend-design",
        query="sandbox diagnostic", operation="design_system", project_name="SandboxProbe"), provider_root=bundle)
    if result.status != "completed":
        raise ValidationFailure(f"{name} probe did not complete: {result.warning}")
    try:
        checks = json.loads(result.output.splitlines()[-1])
    except (ValueError, IndexError) as exc:
        raise ValidationFailure(f"{name} probe did not return diagnostic checks") from exc
    if not isinstance(checks, dict) or set(checks) != expected or any(type(value) is not bool for value in checks.values()):
        raise ValidationFailure(f"{name} probe returned incomplete or invalid checks")
    return checks


def _exec_probe(executable: str, arguments: list[str], name: str) -> str:
    # An allowed exec replaces this probe. Its replacement prints false using
    # the same output contract, so an escape cannot masquerade as denied exec.
    return f'''import json,os
try:
    os.execv({executable!r}, {arguments!r})
except OSError:
    print('## Design System: SandboxProbe\\n'+json.dumps({{{name!r}:True}}))
'''


def qualify(root: Path) -> dict:
    capability = ProviderExecutor.sandbox_capability()
    if not capability["supported"]:
        return {**capability, "qualified": False}
    catalog = load_catalog(root)
    checks = {}
    baselines = {}
    try:
        with ExitStack() as stack, tempfile.TemporaryDirectory(prefix="ea-sandbox-probe-") as temporary:
            base = Path(temporary).resolve()
            bundle = base / "bundle"
            scripts = bundle / "scripts"
            scripts.mkdir(parents=True)
            (bundle / "data").mkdir()
            (bundle / "data/fixture.txt").write_text("snapshot diagnostic", encoding="utf-8")
            secret = base / "outside.txt"
            secret.write_text("sandbox diagnostic only", encoding="utf-8")
            outside_write = base / "unexpected.txt"
            ipv4, endpoint4 = _listener(stack, socket.AF_INET)
            baselines["network_ipv4"] = True
            ipv6, endpoint6 = _listener(stack, socket.AF_INET6)
            baselines["network_ipv6"] = True
            positive = '''import json
from pathlib import Path
snapshot = Path(__file__).parent.parent / 'data/fixture.txt'
work = Path('allowed.txt')
work.write_text('private diagnostic', encoding='utf-8')
print('## Design System: SandboxProbe\\n'+json.dumps({
    'positive_execution':True,
    'snapshot_read':snapshot.read_text(encoding='utf-8')=='snapshot diagnostic',
    'private_work_write':work.read_text(encoding='utf-8')=='private diagnostic'}))
'''
            checks.update(_invoke(catalog, bundle, positive, "positive", {
                "positive_execution", "snapshot_read", "private_work_write"}))
            executable = str(ProviderExecutor._runtime_executable())
            probe = f'''import json,os,socket,subprocess,sys
def denied(operation):
    try:
        operation()
    except (OSError,PermissionError):
        return True
    return False
def connect(family,endpoint):
    with socket.socket(family,socket.SOCK_STREAM) as client:
        client.settimeout(2)
        client.connect(endpoint)
checks={{}}
checks['network_ipv4']=denied(lambda:connect(socket.AF_INET,{endpoint4!r}))
checks['network_ipv6']=denied(lambda:connect(socket.AF_INET6,{endpoint6!r}))
checks['outside_read']=denied(lambda:open({str(secret)!r}).read())
checks['outside_write']=denied(lambda:open({str(outside_write)!r},'w').write('x'))
checks['snapshot_write']=denied(lambda:open(__file__,'a').write('x'))
checks['child_process']=denied(lambda:subprocess.run([{executable!r},'-I','-S','-c','pass'],check=False))
print('## Design System: SandboxProbe\\n'+json.dumps(checks))
'''
            checks.update(_invoke(catalog, bundle, probe, "boundaries", {
                "network_ipv4", "network_ipv6", "outside_read", "outside_write", "snapshot_write", "child_process"}))
            replacement = "import json;print('## Design System: SandboxProbe\\n'+json.dumps({'same_python_exec':False}))"
            checks.update(_invoke(catalog, bundle, _exec_probe(executable, [
                executable, "-I", "-S", "-c", replacement], "same_python_exec"), "python-exec", {"same_python_exec"}))
            if os.name == "nt":
                extra = str(Path(os.environ.get("SYSTEMROOT", "C:/Windows")) / "System32/cmd.exe")
                extra_arguments = [extra, "/d", "/c", 'echo ## Design System: SandboxProbe & echo {"extra_exec":false}']
            else:
                extra = "/bin/sh"
                extra_arguments = [extra, "-c", "printf '%s\\n' '## Design System: SandboxProbe' '{\"extra_exec\":false}'"]
            baseline = subprocess.run(extra_arguments, stdin=subprocess.DEVNULL, capture_output=True, timeout=5, check=True)
            if json.loads(baseline.stdout.splitlines()[-1]) != {"extra_exec": False}:
                raise ValidationFailure("extra executable baseline did not complete")
            checks.update(_invoke(catalog, bundle, _exec_probe(extra, extra_arguments, "extra_exec"), "extra-exec", {"extra_exec"}))
            # Detect a connection independently of the Provider's own result.
            for name, listener in (("network_ipv4", ipv4), ("network_ipv6", ipv6)):
                try:
                    accepted, _ = listener.accept()
                except BlockingIOError:
                    pass
                else:
                    accepted.close()
                    checks[name] = False
            if outside_write.exists():
                checks["outside_write"] = False
            passed = all(checks.values())
            return {**capability, "qualified": passed, "checks": checks, "baselines": baselines,
                    "reason": None if passed else "sandbox escape diagnostic did not satisfy every boundary"}
    except (OSError, subprocess.SubprocessError, ValidationFailure, ValueError, IndexError) as exc:
        return {**capability, "qualified": False, "checks": checks, "baselines": baselines,
                "reason": "sandbox execution could not be qualified: " + str(exc)}
