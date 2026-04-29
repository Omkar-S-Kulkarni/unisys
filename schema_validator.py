import json
from jsonschema import Draft7Validator
from typing import Any


def load_contracts_schema(schema_path: str) -> dict:
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_contract_subschema(contract_schema: dict, contract_name: str) -> dict:
    return contract_schema.get("properties", {}).get(contract_name, {})


def validate_payload(schema: dict, payload: Any) -> tuple[bool, list[dict]]:
    validator = Draft7Validator(schema)
    errors = []
    for err in validator.iter_errors(payload):
        errors.append({
            "path": list(err.absolute_path),
            "message": err.message,
        })
    return len(errors) == 0, errors
