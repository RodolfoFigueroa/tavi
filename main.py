import os
from langchain_core.messages import HumanMessage
import duckdb
import pandas as pd
from typing import Literal
from langchain_core.tools import tool
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode
from langchain_anthropic import ChatAnthropic
from dotenv import load_dotenv

load_dotenv()

# 1. Ephemeral memory for your Pandas DataFrames
session_memory = {}

# 2. Tool: Fetch external data
@tool
def fetch_temperatures_by_location(region_name: str) -> str:
    """Fetches temperature coordinate data and saves it locally as 'local_temps'."""
    # Mock data representing your API call
    df = pd.DataFrame({
        "latitude": [19.4326, 19.4327],
        "longitude": [-99.1332, -99.1333],
        "avg_temp": [36.5, 38.1]
    })
    session_memory['local_temps'] = df
    return f"Success: Data for {region_name} saved as 'local_temps' table."

# 3. Tool: Execute DuckDB Spatial Query
@tool
def execute_spatial_query(sql_query: str) -> str:
    """Executes a DuckDB query. Can join 'local_temps' with pg_db tables."""
    con = duckdb.connect()
    try:
        # Load spatial extension
        con.execute("INSTALL spatial; LOAD spatial;")
        
        # NOTE: For this initial test, we will just query the local table
        # Once this works, you will add your PostGIS ATTACH command here.
        if 'local_temps' in session_memory:
            con.register('local_temps', session_memory['local_temps'])
            
        result_df = con.execute(sql_query).df()
        return result_df.to_string()
    except Exception as e:
        return f"SQL Error: {str(e)}"
    finally:
        con.close()

# Group the tools
tools = [fetch_temperatures_by_location, execute_spatial_query]


# Initialize your LLM and bind the tools to it
llm = ChatAnthropic(model_name="claude-sonnet-4-6")
llm_with_tools = llm.bind_tools(tools)

# Node 1: The Reasoner (LLM)
def call_model(state: MessagesState):
    """Passes the current state to the LLM to decide what to do next."""
    # This is where your massive System Prompt goes
    system_prompt = {
        "role": "system", 
        "content": "You are a spatial data assistant. Use your tools to fetch data and query it."
    }
    messages = [system_prompt] + state["messages"]
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}

# Node 2: The Executor (Tools)
# LangGraph has a prebuilt ToolNode that handles executing the tools and returning the result
tool_node = ToolNode(tools)


# Initialize the graph
workflow = StateGraph(MessagesState)

# Add our two nodes
workflow.add_node("agent", call_model)
workflow.add_node("tools", tool_node)

# Define the flow
workflow.add_edge(START, "agent")

# Conditional edge: If the agent calls a tool, go to 'tools'. Else, go to END.
def should_continue(state: MessagesState) -> Literal["tools", END]:
    last_message = state["messages"][-1]
    if last_message.tool_calls:
        return "tools"
    return END

workflow.add_conditional_edges("agent", should_continue)
workflow.add_edge("tools", "agent")

# Compile the graph into an executable application
app = workflow.compile()


inputs = {"messages": [HumanMessage(content="Fetch the temperatures for Mexico City, then tell me the maximum temperature from that data.")]}

# Stream the execution so you can see LangGraph working!
for event in app.stream(inputs, stream_mode="values"):
    last_message = event["messages"][-1]
    last_message.pretty_print()