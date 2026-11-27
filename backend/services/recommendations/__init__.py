"""Context-aware recommendation layer.

Pipeline: governance findings -> context builder (evidence bundle per
resource) -> deterministic templates -> optional LLM rewrite -> validator ->
cached, structured recommendations. The deterministic engine owns every
number, state and score; the LLM may only rephrase and correlate, and any
output that fails validation is replaced by the template.
"""
