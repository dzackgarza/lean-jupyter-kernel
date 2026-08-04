"""JupyterLab prebuilt extension: Lean 4 syntax highlighting for nbdsl cells."""

# Written by the hatch version build hook from the package.json version, which is
# itself the generated projection of release.toml. No fallback: importing this
# package from an unbuilt tree must fail rather than report a made-up version.
from ._version import __version__

__all__ = ["__version__"]


def _jupyter_labextension_paths():
    return [{"src": "labextension", "dest": "jupyterlab_nbdsl"}]
