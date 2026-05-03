"""
agents/validator.py
 
Validates the modification plan produced by the modifier agent.
Checks for SQL correctness, schema consistency, safety, and completeness.
"""
import json
from langchain_core.messages import HumanMessage, SystemMessage
from ..config import get_llm, MAX_VALIDATION_ITERATIONS
from ..state import GraphState
from ..utils.db_utils import validate_sql_syntax




_SYSTEM_PROMPT = """You are an expert database engineer tasked with generating precise, safe SQLite modification plans.
 
You will receive:
1. The current database schema
2. The user's modification request
3. Clarification Q&A (if any)
4. Validator feedback (if this is a refinement iteration)
5. Modification history so far
 
Your output MUST be valid JSON with this exact structure:
{
  "description": "Plain-English summary of what will be changed and why",
  "sql_statements": [
    "SQL statement 1;",
    "SQL statement 2;"
  ],
  "warnings": ["Any important warnings about data loss, irreversibility, etc."]
}
 
CRITICAL JSON FORMATTING RULES:
- Every string value MUST be delimited with double-quote characters (")
- NEVER use backslash-escaped quotes (\\") as string delimiters inside the JSON
- Multi-line SQL must be written as a single line — replace any real newlines inside SQL strings with a space
- Do NOT use \\n inside JSON string values; keep each SQL statement on one line
- Each element of sql_statements must be a single, self-contained SQL string ending with a semicolon
 
SQL RULES:
- Generate ONLY valid SQLite SQL
- Order statements correctly (create tables before adding FK references, etc.)
- Use IF NOT EXISTS / IF EXISTS where appropriate to make statements idempotent
- Preserve all existing data unless the user explicitly asked to delete something
- For ALTER TABLE: SQLite only supports ADD COLUMN and RENAME – use CREATE TABLE + data copy pattern for other changes
- Include PRAGMA foreign_keys = ON; at the start if any FK changes are involved
- Each SQL string must end with a semicolon
- Do NOT include any explanation outside the JSON
- Do NOT include bare BEGIN / COMMIT / ROLLBACK statements — transaction control is handled externally

DEDUPLICATION RULES (DELETE duplicates, keep one row per group):
- To identify rows to REMOVE, always use this pattern:
    WHERE <pk_col> NOT IN (
      SELECT MIN(<pk_col>) FROM <table> GROUP BY <dup_col1>, <dup_col2>
    )
- NEVER put the primary key column inside GROUP BY when finding duplicates — 
  it is unique by definition so COUNT(*) will never exceed 1.
- NEVER combine GROUP BY with HAVING COUNT(*) > 1 AND <pk> NOT IN (...) 
  in the same subquery — these are mutually exclusive conditions.
- Apply the same NOT IN subquery consistently to UPDATE (nulling FK refs), 
  DELETE from child tables, and DELETE from the main table.

SELF-CHECK RULE:
Before writing your final JSON output, mentally trace through each subquery:
- "Will this subquery actually return the rows I intend?"
- "Is every column referenced in WHERE/HAVING present in GROUP BY or an aggregate?"
- "Would this accidentally match zero rows or all rows?"
If any answer is uncertain, rewrite the subquery using a simpler, more explicit pattern.

TABLE MIGRATION RULES (CREATE new + copy data + DROP old + RENAME):
- Before dropping a table, inspect the schema for any VIEWS that reference it.
  Drop every such view with DROP VIEW IF EXISTS <name>; BEFORE the DROP TABLE statement.
  After the RENAME, recreate every dropped view using its original SQL, updated to
  reference the new column names if they changed.
- Also check for other tables whose FOREIGN KEY references the table being dropped.
  Disable FK enforcement with PRAGMA foreign_keys = OFF; at the very start and
  re-enable with PRAGMA foreign_keys = ON; at the very end.
- Correct statement order for a table migration:
    1. PRAGMA foreign_keys = OFF;
    2. DROP VIEW IF EXISTS <dependent_view>;  (one per dependent view)
    3. CREATE TABLE <new_table> (...);
    4. INSERT INTO <new_table> SELECT ... FROM <old_table>;
    5. DROP TABLE <old_table>;
    6. ALTER TABLE <new_table> RENAME TO <old_table>;
    7. CREATE VIEW <dependent_view> AS ...;  (one per dropped view, updated SQL)
    8. PRAGMA foreign_keys = ON;"""


def run_validator(state: GraphState) -> dict:
    """
    LangGraph node: validates the modification plan.
    Returns updated state with validation_result and routing.
    """
    iterations = state.get("validation_iterations", 0) + 1
    plan = state.get("modification_plan", {})

    if not plan:
        return {
            "validation_result": {
                "approved": False,
                "issues": ["No modification plan was produced."],
                "feedback": "The modifier returned an empty plan.",
                "confidence": "low",
            },
            "validation_iterations": iterations,
            "next_action": "error",
        }
    
    # Syntax dry-run 
    sql_statements = plan.get("sql_statements", [])
    syntax_ok, syntax_err = validate_sql_syntax(state["db_path"], sql_statements)
    syntax_note = "Syntax dry-run PASSED." if syntax_ok else f"Syntax dry-run FAILED: {syntax_err}"   


    # LLM semantic review 
    llm = get_llm(temperature=0.0)
 
    sql_block = "\n".join(sql_statements)
    user_content = f"""DATABASE SCHEMA:
{state['db_schema']}
 
USER REQUEST:
{state['user_request']}
 
PROPOSED PLAN:
Description: {plan.get('description', '')}
Warnings: {plan.get('warnings', [])}
 
SQL STATEMENTS:
{sql_block}
 
SYNTAX CHECK RESULT:
{syntax_note}
"""
    

    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=user_content),
    ]
 
    response = llm.invoke(messages)
    raw = response.content.strip()
 
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()


    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        result = {
            "approved": False,
            "issues": ["Validator produced invalid JSON."],
            "feedback": f"Raw output: {raw[:200]}",
            "confidence": "low",
        }
 
    # Also force fail if syntax dry-run failed
    if not syntax_ok:
        result["approved"] = False
        result["issues"] = [f"Syntax error: {syntax_err}"] + result.get("issues", [])
        result["feedback"] = f"Fix SQL syntax errors. {result.get('feedback', '')}"


    # Routing decision 
    if result.get("approved"):
        next_action = "human_review"
    elif iterations >= MAX_VALIDATION_ITERATIONS:
        # Exhausted retries — still send to human review with a warning
        result["issues"].append(
            f"Maximum validation iterations ({MAX_VALIDATION_ITERATIONS}) reached. "
            "Proceeding to human review with outstanding concerns."
        )
        next_action = "human_review"
    else:
        next_action = "modify"   # send back to modifier for refinement
 
    return {
        "validation_result": result,
        "validation_iterations": iterations,
        "next_action": next_action,
    }
                                                                     
