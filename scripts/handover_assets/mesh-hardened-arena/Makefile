.PHONY: install verify help

install:
	python3 -m pip install -e .

verify:
	PYTHONPATH=src python3 -m mesh_hardened_arena verify-e2e

help:
	@PYTHONPATH=src python3 -m mesh_hardened_arena --help
