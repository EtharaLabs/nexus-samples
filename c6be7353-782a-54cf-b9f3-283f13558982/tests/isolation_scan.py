"""Prove the agent's container holds no engine.

Static checks read the build inputs. The live check builds the agent image and
inspects its filesystem, which is the only evidence that settles the claim.

    python3 isolation_scan.py            static checks only
    python3 isolation_scan.py --live     also build and scan the image
"""

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENV = ROOT / "environment"
# Filenames alone are too common to judge on: pip ships its own index.py. The
# engine is identified by its package directory and by strings only it contains.
ENGINE_MODULES = ("analysis.py", "joinorder.py", "outer_join.py", "sortelim.py",
                  "operators.py", "hashing.py", "refeval.py")
ENGINE_STRINGS = ("null_rejecting", "LAntiMatch", "NullAwareAntiJoin",
                  "HASH_BUILD_THRESHOLD", "carried_collation")


def static() -> list:
    bad = []
    ignore = (ENV / ".dockerignore").read_text(encoding="utf-8").split()
    if "tarnd/" not in ignore:
        bad.append(".dockerignore does not exclude tarnd/ from the agent build context")
    for pattern in ("**/__pycache__", "**/*.pyc", "**/.DS_Store"):
        if pattern not in ignore:
            bad.append(f".dockerignore is missing {pattern}")

    dockerfile = (ENV / "Dockerfile").read_text(encoding="utf-8")
    for line in dockerfile.splitlines():
        if line.strip().startswith("COPY"):
            if any(token in line for token in ("tarnd", "engine", "tarn/")):
                bad.append(f"the agent Dockerfile copies engine material: {line.strip()}")

    compose = (ENV / "docker-compose.yaml").read_text(encoding="utf-8")
    main_block = compose.split("tarnd:")[0]
    if "volumes:" in main_block:
        bad.append("the main service mounts a volume; check it exposes no engine material")

    for path in ENV.rglob("*"):
        if not path.is_file() or "tarnd" in path.relative_to(ENV).parts:
            continue
        if path.name in ENGINE_MODULES:
            bad.append(f"engine module outside tarnd/: {path.relative_to(ENV)}")
        if path.suffix == ".pyc" or "__pycache__" in path.parts:
            bad.append(f"bytecode in the build context: {path.relative_to(ENV)}")
    return bad


def live() -> list:
    tag = "tarn-main-scan"
    build = subprocess.run(["docker", "build", "-q", "-t", tag, "."],
                           cwd=ENV, capture_output=True, text=True, timeout=1800)
    if build.returncode != 0:
        return [f"docker build failed: {build.stderr.strip()[-400:]}"]
    script = (
        "import os\n"
        "bad=[]\n"
        "mods=" + repr(ENGINE_MODULES) + "\n"
        "strs=" + repr(ENGINE_STRINGS) + "\n"
        "for root,dirs,files in os.walk('/'):\n"
        "    if root.startswith(('/proc','/sys','/dev')): continue\n"
        "    if os.path.basename(root)=='tarn' and '__init__.py' in files:\n"
        "        bad.append('tarn package at '+root)\n"
        "    for f in files:\n"
        "        p=os.path.join(root,f)\n"
        "        if f in mods: bad.append(p)\n"
        "        elif f.endswith(('.py','.pyc')):\n"
        "            try:\n"
        "                raw=open(p,'rb').read()\n"
        "            except Exception: continue\n"
        "            if any(s.encode() in raw for s in strs): bad.append(p)\n"
        "print(chr(10).join(bad[:20]) if bad else 'CLEAN')\n"
    )
    run = subprocess.run(["docker", "run", "--rm", "--entrypoint", "python3", tag, "-c", script],
                         capture_output=True, text=True, timeout=900)
    out = (run.stdout or "").strip()
    subprocess.run(["docker", "image", "rm", "-f", tag], capture_output=True)
    if out == "CLEAN":
        return []
    return [f"engine material found inside the agent image: {out}"]


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
