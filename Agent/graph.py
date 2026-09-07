import re
import time

from langchain.agents import create_agent
from langchain_groq import ChatGroq
from langgraph.constants import END
from langgraph.graph import StateGraph
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from states import *
from prompts import *
from tools import *

load_dotenv()
groq_llm = ChatGroq(
    model="openai/gpt-oss-20b",
    temperature=0,
    max_retries=1,
    max_tokens=5000,
    reasoning_effort="medium",
)
gemini_llm = ChatGoogleGenerativeAI(
    model="gemini-3.1-flash-lite",
    temperature=0,
    max_retries=6,
)

def _invoke_structured_with_retry(llm, schema, prompt: str, max_attempts: int = 3):
    structured_llm = llm.with_structured_output(schema, method="function_calling")
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            return structured_llm.invoke(prompt)
        except Exception as e:
            last_error = e
            error_text = str(e)
            is_truncation_error = "Failed to parse tool call arguments" in error_text
            is_rate_limited = "429" in error_text and "rate_limit_exceeded" in error_text
            is_recoverable = is_truncation_error or is_rate_limited or "tool_use_failed" in error_text
            if not is_recoverable or attempt == max_attempts:
                raise
            if is_rate_limited:
                wait_match = re.search(r"try again in (\d+(?:\.\d+)?)s", error_text)
                wait_seconds = float(wait_match.group(1)) + 1 if wait_match else 8.0
                print(f"[structured_output] Rate limited, waiting {wait_seconds:.1f}s "
                      f"before retry {attempt + 1}/{max_attempts}...")
                time.sleep(wait_seconds)
            elif is_truncation_error:
                prompt += (
                    "\n\nNOTE: Your previous attempt was too long and got cut off "
                    "before finishing. Keep every task_description in prose only, "
                    "under ~100 words, with NO markdown code fences or code examples."
                )
                print(f"[structured_output] Output truncated, retrying "
                      f"{attempt + 1}/{max_attempts} with a shorter-output nudge...")
    raise last_error

def planner_agent(state:dict)->dict:
    user_prompt = state["user_prompt"]
    resp = _invoke_structured_with_retry(groq_llm, Plan, Planner_prompt(user_prompt))
    if resp is None:
        raise ValueError("Planner did not return a valid response")
    return {'plan': resp}

def architect_agent(state:dict)->dict:
    plan:Plan = state["plan"]
    resp = _invoke_structured_with_retry(groq_llm, TaskPlan, architect_prompt(plan))
    if resp is None:
        raise ValueError("Planner did not return a valid response")
    resp.plan = plan
    return {'task_plan': resp}

def coder_agent(state: dict) -> dict:
    """LangGraph tool-using coder agent."""
    coder_state: CoderState = state.get("coder_state")
    if coder_state is None:
        coder_state = CoderState(task_plan=state["task_plan"], current_step_idx=0)

    steps = coder_state.task_plan.implementation_steps
    if coder_state.current_step_idx >= len(steps):
        return {"coder_state": coder_state, "status": "DONE"}

    current_task = steps[coder_state.current_step_idx]
    existing_content = read_file.invoke({"path": current_task.filepath})

    system_prompt = coder_system_prompt()
    user_prompt = (
        f"Task: {current_task.task_description}\n"
        f"File: {current_task.filepath}\n"
        f"Existing content:\n{existing_content}\n"
        "Use write_file(path, content) to save your changes."
    )

    coder_tools = [read_file, write_file, list_files, list_file, get_current_directory]
    react_agent = create_agent(gemini_llm, coder_tools)

    max_attempts = 3
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            react_agent.invoke({"messages": [{"role": "system", "content": system_prompt},
                                             {"role": "user", "content": user_prompt}]})
            last_error = None
            break
        except Exception as e:
            last_error = e
            error_text = str(e)
            is_tool_name_error = "was not in request.tools" in error_text or "attempted to call tool" in error_text
            is_tpm_too_large = "413" in error_text and "tokens per minute" in error_text
            is_truncation_error = "Failed to parse tool call arguments" in error_text and not is_tpm_too_large
            is_rate_limited = "429" in error_text and "rate_limit_exceeded" in error_text
            is_recoverable = (
                is_tool_name_error
                or is_truncation_error
                or is_rate_limited
                or "tool_use_failed" in error_text
            )
            # is_tpm_too_large is deliberately excluded from is_recoverable: the
            # request itself exceeded the per-minute token budget, and retrying
            # an identical (or larger) request guarantees the same failure —
            # burning through attempts here only wastes time.
            if is_tpm_too_large or not is_recoverable or attempt == max_attempts:
                break
            if is_rate_limited:
                # Groq's 429 body usually includes "Please try again in X.Xs" — the
                # TPM window just hasn't reset yet. Retrying instantly (as the
                # previous version of this loop did) just hits the same window
                # and fails 3 times in a row for nothing. Wait it out instead.
                wait_match = re.search(r"try again in (\d+(?:\.\d+)?)s", error_text)
                wait_seconds = float(wait_match.group(1)) + 1 if wait_match else 8.0
                print(f"[coder_agent] Rate limited on '{current_task.filepath}', "
                      f"waiting {wait_seconds:.1f}s before retry {attempt + 1}/{max_attempts}...")
                time.sleep(wait_seconds)
            elif is_tool_name_error:
                user_prompt += (
                    "\n\nNOTE: Your previous attempt failed because you called a tool "
                    "that does not exist. You may ONLY call these exact tool names: "
                    "read_file, write_file, list_files, get_current_directory. Do not "
                    "use any prefixed or namespaced tool name."
                )
            else:
                user_prompt += (
                    "\n\nNOTE: Your previous attempt failed because the response was too "
                    "long and got cut off. Keep the implementation concise — avoid "
                    "excessive comments — and if the file is naturally large, write it "
                    "in a single, more compact write_file call."
                )

    if last_error is not None:
        # Skip this step rather than crashing the whole pipeline; the file may be
        # partially written or missing, but subsequent steps can still proceed.
        skip_note = f"{current_task.filepath}: {last_error}"
        print(f"[coder_agent] Skipping '{current_task.filepath}' after "
              f"{max_attempts} failed attempts: {last_error}")
        coder_state.skipped_files.append(skip_note)
        if "tokens per day" in str(last_error) and "429" in str(last_error):
            coder_state.daily_quota_exhausted = True

    coder_state.current_step_idx += 1
    return {"coder_state": coder_state}

graph = StateGraph(dict)
graph.add_node("planner",planner_agent)
graph.add_node("architect",architect_agent)
graph.add_node("coder",coder_agent)
graph.add_edge("planner","architect")
graph.add_edge("architect","coder")

graph.add_conditional_edges(
    "coder",
    lambda s: "END" if s.get("status") == "DONE" else "coder",
    {"END": END, "coder": "coder"}
)

graph.set_entry_point("planner")
agent = graph.compile()


def run_agent(user_prompt: str, project_root: str = None) -> dict:

    init_project_root(project_root)
    result = agent.invoke(
        {"user_prompt": user_prompt},
        {"recursion_limit": 100},
    )
    coder_state = result.get("coder_state")
    result["skipped_files"] = coder_state.skipped_files if coder_state else []
    result["daily_quota_exhausted"] = coder_state.daily_quota_exhausted if coder_state else False
    return result


if __name__ == "__main__":
    result = run_agent("Build a colourful modern todo app in html css and js")
    print("Final State:", result)