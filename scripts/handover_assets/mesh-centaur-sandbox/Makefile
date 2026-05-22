.PHONY: install verify profile live help

install:
	python3 -m pip install -e .

verify:
	PYTHONPATH=src python3 -m mesh_centaur_sandbox verify-e2e

profile:
	PYTHONPATH=src python3 -m mesh_centaur_sandbox verify-profile --json

live:
	PYTHONPATH=src python3 -m mesh_centaur_sandbox verify-live --fake-cluster --json

help:
	@PYTHONPATH=src python3 -m mesh_centaur_sandbox --help
