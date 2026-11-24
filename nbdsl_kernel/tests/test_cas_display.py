"""Display is an inert projection of committed source and runtime data."""
from nbdsl_kernel.cas_display import render_committed, render_inspection


def definition(convention, packet, *, has_packet=True, source=None):
    return {"name": "a_b", "type": "selected type", "scalarConvention": convention,
            "source": source or {"context": [{"name": "B", "role": "selectedStructure"}]},
            "runtime": {"packet": packet, "hasPacket": has_packet}}


def test_integer_and_rational_display_preserves_source():
    for convention, packet, plain, latex in [
        ("integer", -17, "-17", "-17"),
        ("rational", [-2, 3], "-2/3", r"-\frac{2}{3}"),
        ("rational", [2, 1], "2", "2"),
    ]:
        record = definition(convention, packet)
        result = render_committed({"text/plain": "holds"}, {"cas_definitions": [record]})
        assert result["text/plain"] == f"a_b : selected type = {plain}"
        assert latex in result["text/latex"]
        assert r"a\_b" in result["text/latex"]
        assert result["application/vnd.cas.bindings+json"] == [record]


def test_native_two_slot_record_not_rational():
    record = definition("native", [2, 3])
    result = render_committed({"text/plain": "holds"}, {"cas_definitions": [record]})
    assert "Stored data: [2, 3]" in result["text/plain"]
    assert "text/latex" not in result


def test_no_invented_scalar_or_forced_native_value():
    for convention, packet, has_packet in [
        ("rational", [2, 4], True),
        ("rational", [1, 0], True),
        ("integer", True, True),
        ("natural", -1, True),
        ("native", None, False),
    ]:
        record = definition(convention, packet, has_packet=has_packet)
        result = render_committed({"text/plain": "holds"}, {"cas_definitions": [record]})
        assert "text/latex" not in result
        assert result["application/vnd.cas.bindings+json"] == [record]


def test_preserves_explicit_inspection_and_user_output():
    record = definition("integer", 3)
    assert render_committed({"text/plain": "Lean output"}, {}) == {"text/plain": "Lean output"}
    result = render_committed({"text/plain": "holds: P\nselected hypothesis h"},
                              {"cas_definitions": [record]})
    assert result["text/plain"].startswith("holds: P\nselected hypothesis h")
    assert "text/latex" not in result


def test_inspection_separates_types_and_provider_inventory():
    details = {
        "source": {"context": [{"name": "R", "role": "parameter"}],
                   "descriptions": ["Ring"]},
        "runtime": {"hasPacket": False, "availableAtPreparation": False,
                    "completion": {"producer": {"kind": "invocation",
                        "target": {"operation": "op", "input": "typed",
                                   "backend": "backend", "command": "actual-command"}}}},
        "candidates": [
            {"kind": "operation", "name": "multiply", "status": "candidate",
             "type": "R → R", "permittedRegistrationForms": []},
            {"kind": "method", "name": "choose", "status": "unresolved",
             "diagnostic": "missing comparison"},
        ],
    }
    result = render_inspection("x : R", details)
    assert result["application/vnd.cas.binding+json"] is details
    text = result["text/plain"]
    for fragment in ["parameter R : Ring", "Availability at publication: unavailable",
                     "op / typed", "actual-command", "no permitted registration forms",
                     "missing comparison"]:
        assert fragment in text


def test_inspection_uses_actual_routine_frames_without_invented_names():
    direct = {
        "producer": {"kind": "invocation", "target": {"operation": "op.rings.add"}},
        "routines": [{"requestId": 0, "observations": [
            {"role": "entrypoint", "module": "peer", "qualified_name": "add",
             "source": {"path": "/peer.py", "first_line": 12, "sha256": "a" * 64,
                        "text": "def add(x): return x + 1"},
             "code_sha256": "b" * 64, "documentation": None},
            {"role": "delegated", "module": "engine", "qualified_name": "add",
             "documentation": "Actual routine documentation.", "source": None},
        ]}, {"requestId": 1, "observations": []}]
    }
    inherited = {"producer": {"kind": "invocation"}, "routines": [
        {"requestId": 4, "observations": None}
    ]}
    details = {"runtime": {"completions": [direct, inherited]}}
    result = render_inspection("a : ℤ", details)
    text = result["text/plain"]
    for fragment in ["Received request 0", "entrypoint: peer.add", "delegated: engine.add",
                     "/peer.py:12", "a" * 64, "b" * 64,
                     "def add(x): return x + 1", "Actual routine documentation.",
                     "No newly recorded routines in this frame.",
                     "Routine observations were not negotiated."]:
        assert fragment in text
    assert result["application/vnd.cas.binding+json"] is details
