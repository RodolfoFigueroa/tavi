from pathlib import Path


def load_prompt_from_name(name: str) -> str:
    """Load a prompt template from the ``prompts/`` directory by name.

    Args:
        name: Base filename of the prompt (without ``.md`` extension),
            e.g. ``"agent"`` or ``"geo"``.

    Returns:
        The raw text content of ``prompts/{name}.md``.
    """
    prompt_path = Path(__file__).parent.parent.parent.parent / "prompts" / f"{name}.md"
    return prompt_path.read_text(encoding="utf-8")
