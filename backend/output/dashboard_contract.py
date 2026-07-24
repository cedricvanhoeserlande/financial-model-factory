from __future__ import annotations

from typing import Any

from backend.output.dashboard_templates import DASHBOARD_TEMPLATE_CATALOG


DASHBOARD_SPEC_VERSION = "2.0"
TEMPLATE_IDS = set(DASHBOARD_TEMPLATE_CATALOG)
COMPONENT_TYPES = {"kpi", "chart", "table", "text"}
VISUAL_TYPES = {
    "kpi",
    "line",
    "bar",
    "combo",
    "heatmap",
    "tornado",
    "waterfall",
    "statement",
    "table",
    "text",
}


def validate_dashboard_spec(spec: Any, blocks: Any) -> dict[str, Any]:
    """Validate strict v2 wiring while preserving legacy display-intent objects."""
    if not isinstance(spec, dict):
        return _report(False, False, [{"path": "dashboard_spec", "message": "dashboard_spec must be an object."}])
    if spec.get("version") != DASHBOARD_SPEC_VERSION:
        return _report(True, True, [])

    errors: list[dict[str, str]] = []
    required = ("template_id", "title", "subtitle", "currency", "display_units", "sections")
    for key in required:
        if key not in spec:
            errors.append({"path": f"dashboard_spec.{key}", "message": "Required v2 field is missing."})
    if spec.get("template_id") not in TEMPLATE_IDS:
        errors.append({"path": "dashboard_spec.template_id", "message": "Unknown reusable dashboard template."})
    for key in ("title", "subtitle", "currency", "display_units"):
        if not isinstance(spec.get(key), str) or not str(spec.get(key)).strip():
            errors.append({"path": f"dashboard_spec.{key}", "message": "Field must be a non-empty string."})

    block_ids = {
        str(block.get("id"))
        for block in blocks or []
        if isinstance(block, dict) and isinstance(block.get("id"), str)
    }
    sections = spec.get("sections")
    if not isinstance(sections, list) or not sections:
        errors.append({"path": "dashboard_spec.sections", "message": "At least one dashboard section is required."})
        sections = []
    seen_sections: set[str] = set()
    seen_widgets: set[str] = set()
    forbidden_numeric_keys = {"value", "values", "data", "series"}
    for section_index, section in enumerate(sections):
        section_path = f"dashboard_spec.sections[{section_index}]"
        if not isinstance(section, dict):
            errors.append({"path": section_path, "message": "Section must be an object."})
            continue
        section_id = section.get("id")
        if not isinstance(section_id, str) or not section_id.strip():
            errors.append({"path": f"{section_path}.id", "message": "Section id must be a non-empty string."})
        elif section_id in seen_sections:
            errors.append({"path": f"{section_path}.id", "message": "Section id must be unique."})
        else:
            seen_sections.add(section_id)
        if not isinstance(section.get("title"), str) or not str(section.get("title")).strip():
            errors.append({"path": f"{section_path}.title", "message": "Section title must be a non-empty string."})
        widgets = section.get("widgets")
        if not isinstance(widgets, list) or not widgets:
            errors.append({"path": f"{section_path}.widgets", "message": "Section must contain widgets."})
            continue
        for widget_index, widget in enumerate(widgets):
            widget_path = f"{section_path}.widgets[{widget_index}]"
            if not isinstance(widget, dict):
                errors.append({"path": widget_path, "message": "Widget must be an object."})
                continue
            widget_id = widget.get("id")
            if not isinstance(widget_id, str) or not widget_id.strip():
                errors.append({"path": f"{widget_path}.id", "message": "Widget id must be a non-empty string."})
            elif widget_id in seen_widgets:
                errors.append({"path": f"{widget_path}.id", "message": "Widget id must be unique."})
            else:
                seen_widgets.add(widget_id)
            if widget.get("block_id") not in block_ids:
                errors.append({"path": f"{widget_path}.block_id", "message": "Widget must reference an existing output block."})
            if widget.get("component") not in COMPONENT_TYPES:
                errors.append({"path": f"{widget_path}.component", "message": "Unsupported dashboard component."})
            if widget.get("visual") not in VISUAL_TYPES:
                errors.append({"path": f"{widget_path}.visual", "message": "Unsupported dashboard visual."})
            columns = widget.get("columns")
            rows = widget.get("rows")
            if isinstance(columns, bool) or not isinstance(columns, int) or not 1 <= columns <= 12:
                errors.append({"path": f"{widget_path}.columns", "message": "columns must be an integer from 1 to 12."})
            if isinstance(rows, bool) or not isinstance(rows, int) or not 1 <= rows <= 6:
                errors.append({"path": f"{widget_path}.rows", "message": "rows must be an integer from 1 to 6."})
            forbidden = sorted(forbidden_numeric_keys.intersection(widget))
            if forbidden:
                errors.append({"path": widget_path, "message": "Widgets may bind data but may not embed output values: " + ", ".join(forbidden)})
            options = widget.get("options", {})
            if not isinstance(options, dict):
                errors.append({"path": f"{widget_path}.options", "message": "options must be an object."})

    return _report(not errors, False, errors)


def _report(passed: bool, legacy: bool, errors: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "passed": passed,
        "legacy_auto_layout": legacy,
        "version": None if legacy else DASHBOARD_SPEC_VERSION,
        "errors": errors,
        "message": "Legacy dashboard accepted for deterministic auto-layout." if legacy else (
            "Dashboard specification passed." if passed else "Dashboard specification failed."
        ),
    }
