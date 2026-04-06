# Services Directory

This directory is reserved for the runtime modules that implement the closed-loop stages:

- ingest
- trigger
- diagnosis
- planner
- evaluation
- orchestrator
- feedback
- actuators

The first implementation can keep these as modules inside one process, but the directory structure should preserve the stage boundaries so they can be split later if needed.
