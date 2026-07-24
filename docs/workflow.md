# Workflow

## Model Factory workflow

1. **Input Agent:** turns a finance request into a structured specification and
   surfaces assumptions, scope, inputs, outputs, and acceptance criteria.
2. **Modeler:** develops model-local theory, equations, tests, and package
   files through the restricted workspace tool loop.
3. **Deterministic admission:** validates required package structure, imports,
   schemas, output envelope, model-local tests, and input stress cases across
   material drivers.
4. **Review Agent:** independently reads the package, uses execution evidence,
   probes material mechanics, and returns evidence-cited findings plus bounded
   amendments.
5. **Repair loop:** material amendments return to the Modeler. The product
   limits substantive Modeler-Review rounds to three.
6. **Human decision:** a technically admitted/reviewed package still requires
   professional business review before publication.
7. **Regular mode:** changing only assumptions reruns the saved Python package
   locally with no OpenAI call.

## What the recorded example demonstrates

The paint example is a saved result from this workflow. It includes the
specification, model thesis, equation graph, model-local tests, package,
selected deterministic reports, review history, a manual verification record,
and no-OpenAI rerun evidence. It is not regenerated during repository setup.
