import json
import os
from pathlib import Path

import requests
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv
from openai.types.eval_create_params import DataSourceConfigCustom
from openai.types.evals.create_eval_jsonl_run_data_source_param import (
    CreateEvalJSONLRunDataSourceParam,
)


def local_agent_target(query: str, api_url: str) -> str:
    payload = {"message": query}
    response = requests.post(api_url, json=payload, timeout=60)
    response.raise_for_status()
    body = response.json()
    return str(body.get("response", "")).strip()


def load_dataset(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []

    # Standard JSONL path: one JSON object per non-empty line.
    items: list[dict] = []
    line_parse_failed = False
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                items.append(parsed)
            else:
                line_parse_failed = True
                break
        except json.JSONDecodeError:
            line_parse_failed = True
            break

    if items and not line_parse_failed:
        return items

    # Fallback path: parse one or more pretty-printed JSON objects from the file.
    decoder = json.JSONDecoder()
    idx = 0
    length = len(text)
    items = []
    while idx < length:
        while idx < length and text[idx].isspace():
            idx += 1
        if idx >= length:
            break
        obj, idx = decoder.raw_decode(text, idx)
        if isinstance(obj, dict):
            items.append(obj)
    return items


def main() -> None:
    load_dotenv()

    endpoint = os.environ.get(
        "AZURE_AI_PROJECT_ENDPOINT",
        os.environ.get("AZURE_AI_PROJECT_ENDPOINT"),
    )
    model_deployment_name = os.environ.get(
        "AZURE_AI_MODEL_DEPLOYMENT_NAME",
        os.environ.get("WORKIQ_MODEL", "gpt-5-mini"),
    )
    openai_api_version = os.environ.get(
        "OPENAI_API_VERSION",
        os.environ.get("WORKIQ_AZURE_API_VERSION", "2024-08-01-preview"),
    )
    # Some azure-ai-projects versions require OPENAI_API_VERSION to be present in env.
    os.environ["OPENAI_API_VERSION"] = openai_api_version
    eval_name = os.environ.get("EVAL_NAME", "dataset-evaluation")
    run_name = os.environ.get("EVAL_RUN_NAME", "dataset-run")

    api_base = os.environ.get("LOCAL_AGENT_API_BASE", "http://127.0.0.1:5000")
    api_path = os.environ.get("LOCAL_AGENT_API_PATH", "/api/chat")
    api_url = f"{api_base.rstrip('/')}/{api_path.lstrip('/')}"

    dataset_file_name = os.environ.get("EVAL_DATASET_FILE", "dataset.jsonl")
    dataset_file_path = (Path(__file__).parent / dataset_file_name).resolve()
    if not dataset_file_path.exists():
        raise FileNotFoundError(f"Dataset file not found: {dataset_file_path}")

    dataset_items = load_dataset(dataset_file_path)
    run_content = []

    for item in dataset_items:
        query = str(item.get("query", "")).strip()
        if not query:
            continue

        agent_response = local_agent_target(query=query, api_url=api_url)
        run_content.append(
            {
                "item": item,
                "sample": {
                    "output_text": agent_response,
                },
            }
        )

    if not run_content:
        raise ValueError("No valid dataset rows were found for evaluation")

    project_client = AIProjectClient(
        endpoint=endpoint,
        credential=DefaultAzureCredential(),
    )
    openai_client = project_client.get_openai_client()

    data_source_config = DataSourceConfigCustom(
        type="custom",
        item_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "response": {"type": "string"},
                "ground_truth": {"type": "string"},
                "source": {"type": "string"},
            },
            "required": ["query"],
        },
        include_sample_schema=True,
    )

    testing_criteria = [
        {
            "type": "azure_ai_evaluator",
            "name": "coherence",
            "evaluator_name": "builtin.coherence",
            "initialization_parameters": {
                "model": model_deployment_name,
            },
            "data_mapping": {
                "query": "{{item.query}}",
                "response": "{{sample.output_text}}",
            },
        },
        {
        "type": "azure_ai_evaluator",
        "name": "groundedness",
        "evaluator_name": "builtin.groundedness",
        "initialization_parameters": {"deployment_name": model_deployment_name},
        "data_mapping": {
            "query": "{{item.query}}",
            "context": "{{item.query}}",
            "response": "{{sample.output_text}}",
        },
    },
    {
        "type": "azure_ai_evaluator",
        "name": "relevance",
        "evaluator_name": "builtin.relevance",
        "initialization_parameters": {"deployment_name": model_deployment_name},
        "data_mapping": {"query": "{{item.query}}", "response": "{{sample.output_text}}"},
    }
    ]

    eval_object = openai_client.evals.create(
        name=eval_name,
        data_source_config=data_source_config,
        testing_criteria=testing_criteria,
    )

    eval_run = openai_client.evals.runs.create(
        eval_id=eval_object.id,
        name=run_name,
        data_source=CreateEvalJSONLRunDataSourceParam(
            type="jsonl",
            source={
                "type": "file_content",
                "content": run_content,
            },
        ),
    )

    print(f"Created eval: {eval_object.id}")
    print(f"Created run: {eval_run.id}")
    print(f"Local agent endpoint used: {api_url}")


if __name__ == "__main__":
    main()


