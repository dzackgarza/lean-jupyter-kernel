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
from typing import Any

from jupyter_client.kernelspec import KernelSpecManager

from .worker import find_worker_exe


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--project", required=True, help="absolute path to the nbdsl Lake project"
    )
    p.add_argument("--name", default="nbdsl", help="kernelspec name")
    p.add_argument(
        "--prelude-module",
        default="NbDsl.Notebook",
        help="Lean module imported as the notebook prelude — the "
        "DSL a session speaks (default: NbDsl.Notebook)",
    )
    p.add_argument(
        "--display-name",
        default=None,
        help="kernelspec display name (default: derived)",
    )
    p.add_argument(
        "--language-name",
        default="lean4",
        help="language name reported in kernel_info (default: lean4)",
    )
    p.add_argument(
        "--mimetype",
        default="text/x-lean4",
        help="cell mimetype reported in kernel_info — routes "
        "JupyterLab's editor to the registered highlighter "
        "(default: text/x-lean4)",
    )
    p.add_argument(
        "--file-extension",
        default=".lean",
        help="file extension reported in kernel_info (default: .lean)",
    )
    p.add_argument(
        "--init-cell",
        default="",
        help="Lean commands run once after worker start as the "
        "session base (e.g. set_option defaults, opens)",
    )
    p.add_argument(
        "--sandbox",
        action="store_true",
        help="run the Lean worker under bubblewrap (read-only "
        "project/toolchain, no network) for untrusted notebooks",
    )
    args = p.parse_args()

    project = Path(args.project).resolve()
    if not (project / "lean-toolchain").exists():
        sys.exit(f"error: {project} has no lean-toolchain — not a Lean project")
    if find_worker_exe(project) is None:
        sys.exit(
            f"error: worker not built — run `lake build nbdsl_worker` in {project}"
        )

    display = args.display_name or f"{args.prelude_module.split('.')[0]} (Lean 4)"
    spec: dict[str, Any] = {
        "argv": [
            sys.executable,
            "-m",
            "nbdsl_kernel",
            "-f",
            "{connection_file}",
            "--project",
            str(project),
        ],
        "display_name": display,
        "language": args.language_name,
        "interrupt_mode": "message",
        "env": {
            "NBDSL_PRELUDE": args.prelude_module,
            "NBDSL_LANGUAGE_NAME": args.language_name,
            "NBDSL_MIMETYPE": args.mimetype,
            "NBDSL_LANGUAGE_EXT": args.file_extension,
        },
        "metadata": {
            "nbdsl": {
                "project_root": str(project),
                "prelude_module": args.prelude_module,
            }
        },
    }
    if args.init_cell:
        spec["env"]["NBDSL_INIT"] = args.init_cell
    if args.sandbox:
        spec["env"]["NBDSL_SANDBOX"] = "1"
        spec["display_name"] += " [sandboxed]"
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "kernel.json").write_text(json.dumps(spec, indent=2))
        dest = KernelSpecManager().install_kernel_spec(d, args.name, user=True)
    print(f"installed kernelspec '{args.name}' at {dest}")


if __name__ == "__main__":
    main()
