from scripts.benchmark_model_cpu import parse_model_json


def test_parse_model_json_accepts_required_fields() -> None:
    output = """```json
    {
      "first_name": "Mina",
      "last_name": "Patel",
      "job_title": "Product Designer",
      "company": "Northstar Studio",
      "location": "Bengaluru, India",
      "phone_number": "+91 98765 43210",
      "email": "mina@northstar.example",
      "confidence": {},
      "warnings": []
    }
    ```"""

    parsed = parse_model_json(output)

    assert parsed is not None
    assert parsed["email"] == "mina@northstar.example"


def test_parse_model_json_rejects_missing_official_field() -> None:
    assert parse_model_json('{"first_name":"Mina"}') is None
