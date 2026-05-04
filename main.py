from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

from tavi.workflow import app

load_dotenv()

if __name__ == "__main__":
    inputs = {
        "messages": [
            HumanMessage(
                content="Fetch the temperatures for Mexico City, then tell me the maximum temperature from that data."
            )
        ]
    }

    # Stream the execution so you can see LangGraph working!
    for event in app.stream(inputs, stream_mode="values"):
        last_message = event["messages"][-1]
        last_message.pretty_print()
