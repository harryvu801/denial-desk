"""The evaluation system.

Four axes — accuracy, robustness, cost/latency, safety — across two modes: offline suites
run in CI against versioned datasets, and online scoring of sampled production traffic.

This package is not a test suite. Tests answer "does the code do what I wrote"; evals answer
"does the system do what it is for", and the answer is a number that moves. See ADR-013.
"""
