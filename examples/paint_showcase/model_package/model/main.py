from model.assumptions import load_inputs
from model.schedules import run_all
from model.outputs import build_output


def run_model(inputs):
    normalized = load_inputs(inputs)
    schedules = run_all(normalized)
    return build_output(normalized, schedules)
