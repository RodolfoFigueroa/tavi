from pathlib import Path


def load_prompt_from_name(name: str) -> str:
    prompt_path = Path(__file__).parent.parent.parent.parent / "prompts" / f"{name}.md"
    return prompt_path.read_text(encoding="utf-8")
