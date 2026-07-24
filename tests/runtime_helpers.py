from __future__ import annotations

import importlib
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def isolated_runtime(runtime_dir: Path, *, unit_stubs: str | None = None, presentation_agent: bool = False) -> Iterator[None]:
    previous_runtime = os.environ.get("MODEL_FACTORY_RUNTIME_DIR")
    previous_stubs = os.environ.get("MODEL_FACTORY_UNIT_STUBS")
    previous_presentation_bypass = os.environ.get("MODEL_FACTORY_TEST_DISABLE_PRESENTATION_AGENT")
    os.environ["MODEL_FACTORY_RUNTIME_DIR"] = str(runtime_dir)
    if presentation_agent:
        os.environ.pop("MODEL_FACTORY_TEST_DISABLE_PRESENTATION_AGENT", None)
    else:
        os.environ["MODEL_FACTORY_TEST_DISABLE_PRESENTATION_AGENT"] = "1"
    if unit_stubs is not None:
        os.environ["MODEL_FACTORY_UNIT_STUBS"] = unit_stubs
    try:
        yield
    finally:
        if previous_runtime is None:
            os.environ.pop("MODEL_FACTORY_RUNTIME_DIR", None)
        else:
            os.environ["MODEL_FACTORY_RUNTIME_DIR"] = previous_runtime
        if unit_stubs is not None:
            if previous_stubs is None:
                os.environ.pop("MODEL_FACTORY_UNIT_STUBS", None)
            else:
                os.environ["MODEL_FACTORY_UNIT_STUBS"] = previous_stubs
        if previous_presentation_bypass is None:
            os.environ.pop("MODEL_FACTORY_TEST_DISABLE_PRESENTATION_AGENT", None)
        else:
            os.environ["MODEL_FACTORY_TEST_DISABLE_PRESENTATION_AGENT"] = previous_presentation_bypass


def reload_app_runtime_modules():
    from backend.app import (
        model_builder,
        model_context,
        model_conversations,
        model_lifecycle,
        model_loop,
        model_registry,
        model_runs,
        model_spec,
        model_trace,
        model_usage,
        model_workspace,
    )

    importlib.reload(model_trace)
    importlib.reload(model_builder)
    importlib.reload(model_registry)
    importlib.reload(model_context)
    importlib.reload(model_workspace)
    importlib.reload(model_usage)
    importlib.reload(model_conversations)
    importlib.reload(model_spec)
    importlib.reload(model_lifecycle)
    importlib.reload(model_runs)
    return importlib.reload(model_loop), model_registry, model_builder

