"""Kernel launcher: `python -m nbdsl_kernel -f <connection_file> --project <root>`."""

import os
import sys

from ipykernel.kernelapp import IPKernelApp

from .kernel import NbDslKernel


def main():
    argv = sys.argv[1:]
    if "--project" in argv:
        i = argv.index("--project")
        os.environ["NBDSL_PROJECT"] = argv[i + 1]
        del argv[i:i + 2]
    IPKernelApp.launch_instance(argv=argv, kernel_class=NbDslKernel)


if __name__ == "__main__":
    main()
