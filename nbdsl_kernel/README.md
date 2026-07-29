# nbdsl_kernel

The Python side: an ipykernel wrapper (`kernel.py`), the worker client
owning everything fd-shaped (`worker.py`), the wire protocol modeled in
Pydantic (`protocol.py` — raw frames become typed models at the transport
boundary), and the kernelspec installer (`install.py`, see `--help` for the
prelude/init-cell/sandbox knobs).

`tests/` holds the proof suites — roundtrip (the protocol's independent
oracle; its frame codec is deliberately duplicated, do not "deduplicate"),
Jupyter E2E, and the sandbox check. What each proves:
[../docs/development.md](../docs/development.md#test-suites--what-proves-what).

- Kernel modes & recovery: [../docs/architecture.md](../docs/architecture.md)
- Protocol: [../docs/protocol.md](../docs/protocol.md)
- Service deployment: [../docs/deployment.md](../docs/deployment.md)
