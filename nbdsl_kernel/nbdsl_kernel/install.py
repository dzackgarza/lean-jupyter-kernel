"""Kernelspec installer: `python -m nbdsl_kernel.install --project <lean project root>`.

Writes the absolute project root into the kernelspec so the kernel always
starts the worker under the right Lake project (and thus, via elan, the
project-pinned toolchain).
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

from jupyter_client.kernelspec import KernelSpecManager


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project", required=True,
                   help="absolute path to the nbdsl Lake project")
    p.add_argument("--name", default="nbdsl", help="kernelspec name")
    p.add_argument("--sandbox", action="store_true",
                   help="run the Lean worker under bubblewrap (read-only "
                        "project/toolchain, no network) for untrusted notebooks")
    args = p.parse_args()

    project = Path(args.project).resolve()
    if not (project / "lean-toolchain").exists():
        sys.exit(f"error: {project} has no lean-toolchain — not a Lean project")
    worker = project / ".lake/build/bin/nbdsl_worker"
    if not worker.exists():
        sys.exit(f"error: worker not built — run `lake build nbdsl_worker` in {project}")

    spec = {
        "argv": [sys.executable, "-m", "nbdsl_kernel",
                 "-f", "{connection_file}", "--project", str(project)],
        "display_name": "NbDsl (Lean 4)",
        "language": "lean4",
        "interrupt_mode": "message",
        "metadata": {"nbdsl": {"project_root": str(project)}},
    }
    if args.sandbox:
        spec["env"] = {"NBDSL_SANDBOX": "1"}
        spec["display_name"] += " [sandboxed]"
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "kernel.json").write_text(json.dumps(spec, indent=2))
        dest = KernelSpecManager().install_kernel_spec(d, args.name, user=True)
    print(f"installed kernelspec '{args.name}' at {dest}")


if __name__ == "__main__":
    main()
