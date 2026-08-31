"""Vendored third-party code.

`nayactl/` is a copy of Cory Bennett's nayactl (Apache-2.0), the CDC serial
protocol implementation for the Naya Create keyboard. It is vendored here so the
backend is self-contained and can later split into its own repository.

Provenance chain: github.com/Qonfused/nayactl -> D:\\NayaOS\\external\\nayactl
-> this copy. Keep it byte-current with the upstream snapshot; new REMAP protocol
work should be written in openflow_backend.device.remap in a form suitable for a
nayactl pull request rather than forking the vendored tree.
"""
