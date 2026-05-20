# ruff: noqa: T201

import argparse
import contextlib
import json
import os
import sys

import httpx


def _get_base_url(args: argparse.Namespace) -> str:
    return args.url or os.environ.get("TAVI_URL", "http://localhost:8000")


def _get_api_key() -> str:
    key = os.environ.get("TAVI_API_KEY", "")
    if not key:
        print("Error: TAVI_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)
    return key


def _create_conversation(client: httpx.Client) -> str:
    resp = client.post("/conversations")
    resp.raise_for_status()
    return resp.json()["thread_id"]


def _close_conversation(client: httpx.Client, thread_id: str) -> None:
    with contextlib.suppress(httpx.HTTPError):
        client.delete(f"/conversations/{thread_id}")


def _stream_message(client: httpx.Client, thread_id: str, content: str) -> None:
    """POST a message and print streamed tokens as they arrive."""
    with client.stream(
        "POST",
        f"/conversations/{thread_id}/messages",
        json={"content": content},
        timeout=None,  # graph execution can be slow
    ) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            payload = json.loads(line[len("data: ") :])
            event_type = payload.get("type")
            if event_type == "token":
                print(payload["content"], end="", flush=True)
            elif event_type == "error":
                print(f"\n[Server error: {payload.get('detail')}]", file=sys.stderr)
                break
            elif event_type == "done":
                break
    print()  # newline after the streamed response


def main() -> None:
    parser = argparse.ArgumentParser(description="Tavi interactive client")
    parser.add_argument(
        "--url",
        metavar="URL",
        help="Server base URL (default: $TAVI_URL or http://localhost:8000)",
    )
    args = parser.parse_args()

    base_url = _get_base_url(args)
    headers = {"X-API-Key": _get_api_key()}

    with httpx.Client(base_url=base_url, headers=headers) as client:
        print(f"Connecting to {base_url} …")
        try:
            thread_id = _create_conversation(client)
        except httpx.HTTPStatusError as exc:
            print(
                f"Error: {exc.response.status_code} {exc.response.text}",
                file=sys.stderr,
            )
            sys.exit(1)
        except httpx.ConnectError:
            print(f"Error: could not connect to {base_url}", file=sys.stderr)
            sys.exit(1)

        print(f"Conversation started  (thread: {thread_id})")
        print("Enter a message and press Enter. Leave blank or press Ctrl+C to exit.\n")

        try:
            while True:
                try:
                    user_input = input("You: ").strip()
                except EOFError:
                    break
                if not user_input:
                    break

                print("Assistant: ", end="", flush=True)
                try:
                    _stream_message(client, thread_id, user_input)
                except httpx.HTTPStatusError as exc:
                    print(
                        f"\nError: {exc.response.status_code} {exc.response.text}",
                        file=sys.stderr,
                    )
        except KeyboardInterrupt:
            print()
        finally:
            print("Closing conversation...")
            _close_conversation(client, thread_id)


if __name__ == "__main__":
    main()
