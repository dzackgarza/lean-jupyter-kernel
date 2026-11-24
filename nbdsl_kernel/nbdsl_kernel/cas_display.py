"""Pure formatting of committed mathematical observation data.

The source reader owns the native type, selections and meaning; the
runtime owns the packet and its provenance. In particular, a two-element
JSON array is not a rational unless the retained native type says it is.
No formatter calls a worker, a provider, or an expression evaluator.
"""
from __future__ import annotations

import json
from math import gcd
from typing import Any


def _record(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _array(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(", ", ": "))


def _scalar(definition: dict[str, Any]) -> tuple[str, str] | None:
    """Use the convention from the actual checked source type, not shape alone."""
    runtime = _record(definition.get("runtime"))
    if not runtime.get("hasPacket"):
        return None
    packet = runtime.get("packet")
    if definition.get("scalarConvention") in {"natural", "integer"} and type(packet) is int:
        if definition["scalarConvention"] == "natural" and packet < 0:
            return None
        return str(packet), str(packet)
    if definition.get("scalarConvention") == "rational" and isinstance(packet, list):
        if len(packet) != 2 or any(type(part) is not int for part in packet):
            return None
        numerator, denominator = packet
        if denominator <= 0 or gcd(numerator, denominator) != 1:
            return None
        if denominator == 1:
            return str(numerator), str(numerator)
        sign = "-" if numerator < 0 else ""
        return (f"{numerator}/{denominator}",
                sign + r"\frac{" + str(abs(numerator)) + "}{" + str(denominator) + "}")
    return None


def _latex_text(text: str) -> str:
    # Input names/types are inert text, not executable TeX from the source.
    escaping = {
        "\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "%": r"\%",
        "$": r"\$", "&": r"\&", "#": r"\#", "_": r"\_",
        "^": r"\textasciicircum{}", "~": r"\textasciitilde{}",
    }
    return "".join(escaping.get(char, char) for char in text)


def _binding_text(binding: dict[str, Any]) -> str:
    name = str(binding.get("name", ""))
    typ = str(binding.get("type", ""))
    head = f"{name} : {typ}"
    runtime = _record(binding.get("runtime"))
    scalar = _scalar(binding)
    if scalar is not None:
        return f"{head} = {scalar[0]}"
    if not runtime:
        return head + " (no retained computational value)"
    if runtime.get("hasPacket"):
        return head + "\nStored data: " + _json(runtime.get("packet"))
    return head + " (retained native value; not materialized for display)"


def render_committed(data: dict[str, object], metadata: dict[str, object]) -> dict[str, object]:
    """Add useful data/LaTeX to one already committed event; never emit separately."""
    definitions = [_record(item) for item in _array(metadata.get("cas_definitions"))]
    if not definitions:
        return data
    output = dict(data)
    original = str(output["text/plain"])
    rendered = "\n".join(_binding_text(item) for item in definitions)
    output["text/plain"] = rendered if original == "holds" else original + "\n" + rendered
    # Keep all selected context, evidence, and provenance intact alongside the
    # rendered text. Native values and unknown encodings are not evaluated.
    output["application/vnd.cas.bindings+json"] = definitions
    if len(definitions) == 1 and original == "holds":
        definition = definitions[0]
        scalar = _scalar(definition)
        if scalar is not None and "text/latex" not in output:
            name = _latex_text(str(definition["name"]))
            typ = _latex_text(str(definition["type"]))
            output["text/latex"] = (
                r"$\text{" + name + r"} : \text{" + typ + r"} = " + scalar[1] + "$"
            )
    return output


def render_inspection(text: str, details: dict[str, object]) -> dict[str, object]:
    """Inspect only the immutable descriptor prepared at publication."""
    lines = [text]
    source = _record(details.get("source"))
    descriptions = _array(source.get("descriptions"))
    context = _array(source.get("context"))
    if context:
        lines.append("\nSelected source context:")
        for index, entry in enumerate(context):
            declaration = _record(entry)
            description = descriptions[index] if index < len(descriptions) else ""
            lines.append(f"  {declaration.get('role', '')} {declaration.get('name', '')}"
                         + (f" : {description}" if description else ""))
    runtime = _record(details.get("runtime"))
    if runtime:
        if runtime.get("hasPacket"):
            lines.append("\nStored data: " + _json(runtime.get("packet")))
        else:
            lines.append("\nRetained native value (not evaluated by inspection).")
        if "availableAtPreparation" in runtime:
            lines.append("Availability at publication: " +
                         ("available" if runtime["availableAtPreparation"] else "unavailable"))
        completions = [_record(item) for item in _array(runtime.get("completions"))]
        if not completions:
            completion = _record(runtime.get("completion"))
            if completion:
                completions = [completion]
        for completion in completions:
            producer = _record(completion.get("producer"))
            target = _record(producer.get("target"))
            if producer:
                lines.append("\nActual producer: " + str(producer.get("kind", "")))
            if target.get("operation"):
                lines.append("  " + str(target["operation"]) + " / " + str(target.get("input", "")))
                lines.append("  Backend: " + str(target.get("backend", "")))
                if target.get("command"):
                    lines.append("  Executable configuration: " +
                                 _json([target["command"], *_array(target.get("arguments"))]))
            for frame in _array(completion.get("routines")):
                observation = _record(frame)
                routines = observation.get("observations")
                lines.append(f"  Received request {observation.get('requestId', '')}:")
                if routines is None:
                    lines.append("    Routine observations were not negotiated.")
                elif not routines:
                    lines.append("    No newly recorded routines in this frame.")
                for item in _array(routines):
                    routine = _record(item)
                    qualified = f"{routine.get('module', '')}.{routine.get('qualified_name', '')}"
                    lines.append(f"    {routine.get('role', '')}: {qualified}")
                    source = _record(routine.get("source"))
                    doc = routine.get("documentation")
                    if routine.get("code_sha256"):
                        lines.append(f"    Code SHA-256: {routine['code_sha256']}")
                    if source:
                        lines.append(f"    Source: {source.get('path', '')}:{source.get('first_line', '')}")
                        lines.append(f"    Source file SHA-256: {source.get('sha256', '')}")
                    if doc:
                        lines.append("    Documentation: " + str(doc))
                    elif source:
                        lines.append("    Source excerpt:\n" + str(source.get("text", "")))
                    else:
                        lines.append("    Primary documentation/source unavailable.")
    candidates = [_record(item) for item in _array(details.get("candidates"))]
    if candidates:
        lines.append("\nSource-derived candidates (not a promise of implementation):")
        for candidate in candidates:
            forms = _array(candidate.get("permittedRegistrationForms"))
            status = candidate.get("status", "unknown")
            line = f"  {candidate.get('kind', '')} {candidate.get('name', '')}: {status}"
            if candidate.get("type"):
                line += " — " + str(candidate["type"])
            if status == "unresolved":
                line += " — " + str(candidate.get("diagnostic", ""))
            elif not forms:
                line += " — no permitted registration forms"
            else:
                line += f" — {len(forms)} permitted registration form(s)"
            lines.append(line)
    return {"text/plain": "\n".join(lines), "application/vnd.cas.binding+json": details}
