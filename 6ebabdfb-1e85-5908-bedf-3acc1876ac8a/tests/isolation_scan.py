"""Prove the agent's container holds no engine.

Static checks read the build inputs. The live check builds the agent image and scans
its filesystem for the engine package or strings only the engine contains, which is
the only evidence that settles the claim.

    python3 isolation_scan.py          static checks only
    python3 isolation_scan.py --live   also build and scan the image
"""

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENV = ROOT / "environment"
ENGINE_MODULES = ("decide.py", "closure.py", "conditions.py")
ENGINE_STRINGS = ("_not_action_specificity", "order_key", "WARDD", "def answer(verb")


def static():
    bad = []
    ignore = (ENV / ".dockerignore").read_text().split()
    if "wardd/" not in ignore:
        bad.append(".dockerignore does not exclude wardd/ from the agent build context")
    for pattern in ("**/__pycache__", "**/*.pyc"):
        if pattern not in ignore:
            bad.append(f".dockerignore is missing {pattern}")
    for line in (ENV / "Dockerfile").read_text().splitlines():
        if line.strip().startswith("COPY") and ("wardd" in line or "engine" in line):
            bad.append(f"the agent Dockerfile copies engine material: {line.strip()}")
    for path in ENV.rglob("*"):
        if not path.is_file() or "wardd" in path.relative_to(ENV).parts:
            continue
        if path.name in ENGINE_MODULES:
            bad.append(f"engine module outside wardd/: {path.relative_to(ENV)}")
    return bad


def live():
    tag = "ward-main-scan"
    build = subprocess.run(["docker", "build", "-q", "-t", tag, "."], cwd=ENV,
                           capture_output=True, text=True, timeout=1800)
    if build.returncode != 0:
        return [f"docker build failed: {build.stderr.strip()[-400:]}"]
    script = (
        "import os\n"
        "bad=[]\n"
        "mods=" + repr(ENGINE_MODULES) + "\n"
        "strs=" + repr(ENGINE_STRINGS) + "\n"
        "top=os.path.abspath(os.sep)\n"
        "for root,dirs,files in os.walk(top):\n"
        "  if os.path.relpath(root,top).split(os.sep)[0] in ('proc','sys','dev'):\n"
        "    dirs[:]=[]; continue\n"
        "  if os.path.basename(root)=='ward' and '__init__.py' in files:\n"
        "    bad.append('ward package at '+root)\n"
        "  for f in files:\n"
        "    p=os.path.join(root,f)\n"
        "    if f in mods: bad.append(p)\n"
        "    elif f.endswith(('.py','.pyc')):\n"
        "      try: raw=open(p,'rb').read()\n"
        "      except Exception: continue\n"
        "      if any(s.encode() in raw for s in strs): bad.append(p)\n"
        "print(chr(10).join(bad[:20]) if bad else 'CLEAN')\n"
    )
    run = subprocess.run(["docker", "run", "--rm", "--entrypoint", "python3", tag, "-c", script],
                         capture_output=True, text=True, timeout=900)
    subprocess.run(["docker", "image", "rm", "-f", tag], capture_output=True)
    out = (run.stdout or "").strip()
    return [] if out == "CLEAN" else [f"engine material in the agent image: {out}"]


def main() -> int:
    problems = static()
    print(f"static checks: {'clean' if not problems else str(len(problems)) + ' problem(s)'}")
    for item in problems:
        print(f"  {item}")
    if "--live" in sys.argv:
        live_problems = live()
        print(f"live image scan: {'clean' if not live_problems else 'FAILED'}")
        for item in live_problems:
            print(f"  {item}")
        problems += live_problems
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
