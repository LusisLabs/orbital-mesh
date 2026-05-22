.PHONY: install verify verify-json help

install:
	python3 -m pip install -e .

verify:
	PYTHONPATH=src python3 -m mesh_darkharness verify-e2e

verify-json:
	PYTHONPATH=src python3 -m mesh_darkharness verify-e2e --json

help:
	@PYTHONPATH=src python3 -m mesh_darkharness --help
