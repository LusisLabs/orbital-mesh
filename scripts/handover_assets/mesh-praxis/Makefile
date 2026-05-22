.PHONY: install verify demo help

install:
	python3 -m pip install -e .

verify:
	PYTHONPATH=src python3 -m mesh_praxis verify-e2e

demo:
	PYTHONPATH=src python3 -m mesh_praxis demo-pipeline --json

help:
	@PYTHONPATH=src python3 -m mesh_praxis --help
