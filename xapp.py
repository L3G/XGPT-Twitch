import os
import json
import re
import requests
import random
from flask import Flask, request, Response
import openai  # <-- Uses OpenAI usage

app = Flask(__name__)

##################################################
# Global conversation history
##################################################
CONVERSATION_HISTORY = []

##################################################
# 1) Load banned words from message.txt at startup
##################################################
BANNED_WORDS = []
try:
    with open("message.txt", "r", encoding="utf-8") as f:
        for line in f:
            w = line.strip().lower()
            if w:
                BANNED_WORDS.append(w)
except FileNotFoundError:
    pass

##################################################
# 2) Set credentials
##################################################
GOOGLE_API_KEY = "AIzaSyDEpAVpDeJ4nHcEk8nkqN3MHpahM0VDcn4"
GOOGLE_SEARCH_CX = "3099754d9b7fb4d0f"

# We will reuse CLOUDFLARE_API_TOKEN for the OpenAI key to "keep the API keys the same"
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "imctBDLywoQ2ObbR3fmpaGDi6UrrDiQ_IxwwEQfO")

# Initialize openai with the same token
openai.api_key = os.getenv("OPENAI_API_KEY", "YOUR_OPENAI_API_KEY")

##################################################
# 3) browse_internet function (unchanged)
##################################################
def browse_internet(search_query: str) -> str:
    """
    Makes a real request to the Google Custom Search API
    and returns a short string describing the top results.
    """
    try:
        response = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={
                "key": GOOGLE_API_KEY,
                "cx": GOOGLE_SEARCH_CX,
                "q": search_query,
            },
            timeout=10,
        )
        if response.status_code != 200:
            return f"Google API error: {response.status_code} {response.text}"

        data = response.json()
        items = data.get("items", [])
        if not items:
            return "No search results found."

        # Format a short summary of the top 3 results
        snippets = []
        for i, item in enumerate(items[:3], start=1):
            title = item.get("title", "")
            snippet = item.get("snippet", "")
            # Do NOT include links in your response
            snippets.append(f"Result {i}: {title}\nSnippet: {snippet}")

        return "\n\n".join(snippets)
    except Exception as e:
        return f"Error performing Google search: {str(e)}"


##################################################
# 4) Tools: One function for searching
##################################################
tools = [
    {
        "type": "function",
        "function": {
            "name": "browse_internet",
            "description": (
                "Search the internet for any query. Returns the top 3 results' titles and snippets. "
                "Does NOT include hyperlinks in its output. If you need external info, call this."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The user-provided query or search terms."
                    }
                },
                "required": ["query"],
                "additionalProperties": False
            },
            "strict": True
        }
    }
]


##################################################
# 5) Helper: OpenAI chat function
##################################################
def run_openai_chat(model: str, messages: list, params: dict = None) -> dict:
    """
    Calls the OpenAI ChatCompletion API with a given model, messages array,
    and function calling 'tools'. The `params` dict can include fields
    like temperature, top_p, frequency_penalty, etc.
    """
    if params is None:
        params = {}

    try:
        # Use the ChatCompletion "tools" for function calling
        completion = openai.chat.completions.create(
            model=model,
            messages=[
                {"role": msg["role"], "content": msg["content"]}
                for msg in messages
            ],
            tools=tools,
            temperature=params.get("temperature", 1.0),
            top_p=params.get("top_p", 1.0),
            frequency_penalty=params.get("frequency_penalty", 0.0),
            presence_penalty=params.get("presence_penalty", 0.0),
            max_tokens=params.get("max_tokens", 256),
        )

        # If there's no textual assistant message, default to an empty string
        assistant_text = completion.choices[0].message.get("content", "")
        tool_calls = completion.choices[0].message.tool_calls

        return {
            "result": {"response": assistant_text},
            "success": True,
            "errors": [],
            "messages": [],
            "tool_calls": tool_calls
        }

    except Exception as e:
        return {
            "result": {"response": f"OpenAI error: {e}"},
            "success": False,
            "errors": [str(e)],
            "messages": [],
            "tool_calls": []
        }


##################################################
# 6) Minimal Flask app with censorship & function calls
##################################################
@app.route('/answer', methods=['GET'])
def answer():
    question = request.args.get('question', '').strip()

    # Always return 200 (OK) so StreamElements can parse the result
    if not question:
        return Response(
            "No question provided. Usage: ?question=Your+Message+Here",
            200,
            mimetype="text/plain; charset=utf-8"
        )

    # Keep the last 4 messages (2 user–assistant turns)
    global CONVERSATION_HISTORY
    CONVERSATION_HISTORY = CONVERSATION_HISTORY[-4:]

    messages = []
    penis_size = random.randint(-1, 18)

    # Decide system prompt & parameters
    if question.startswith("pp"):
        dev_message = {
            "role": "system",
            "content": (
                "As a chatbot, my primary directive is to entertain and maintain decorum within the Twitch community. "
                "Bully the user as well. Incorporate previous chat messages if it makes sense. "
                "While I should generate humorous and vulgar content regarding penis size, I must keep it free of slurs. "
                "Use words like fuck, shit, ass, bitch, dumbass, and fucker. "
                "Avoid links. Keep it funny without crossing the line!"
            )
        }
        messages = [dev_message] + CONVERSATION_HISTORY + [
            {"role": "user", "content": f"My penis size is {penis_size} inches."}
        ]
        openai_params = {
            "temperature": 1.0,
            "top_p": 0.6,
            "frequency_penalty": 1.2,
            "presence_penalty": 0.9,
            "max_tokens": 200
        }
    else:
        # System prompt
        dev_message = {
            "role": "system",
            "content": (
                "You are a twitch chat bot that bullies the user and streamer with excessive and vulgar language (but nothing that would get someone cancelled such as slurs and the r word)."
                "You aren't racist so don't use the n word (even if it ends with a)."
                "Use words like fuck, shit, ass, bitch, dumbass, fucker, though. "
                "You MUST answer the question wrong. You MUST keep responses less than 250 characters. "
                "Do NOT include any links in your response. "
                "If the question needs online info, write 'FUNCTION_CALL: browse_internet' followed by "
                "the search query you need. Only call it once."
                "You CANNOT use the character '/' in your response."
            )
        }
        messages = [dev_message] + CONVERSATION_HISTORY + [
            {"role": "user", "content": question}
        ]
        openai_params = {}

    # 1) First call to OpenAI
    model_name = "gpt-4o-mini"
    first_resp = run_openai_chat(model_name, messages, openai_params)

    if not first_resp["success"]:
        return Response(
            first_resp["result"]["response"],
            200,
            mimetype="text/plain; charset=utf-8"
        )

    # 2) Check if model called the function(s)
    final_answer = first_resp["result"]["response"]
    tool_calls = first_resp.get("tool_calls") or []

    if tool_calls:
        # Append the model's tool_call message to conversation
        messages.append({
            "role": "assistant",
            "content": final_answer
        })
        # For each function call, parse arguments, call the function, append the result
        for tc in tool_calls:
            fn_name = tc.function.name
            raw_args = tc.function.arguments
            try:
                parsed_args = json.loads(raw_args)
            except:
                parsed_args = {}

            result_str = ""
            if fn_name == "browse_internet":
                q = parsed_args.get("query", question)
                result_str = browse_internet(q)
            else:
                result_str = f"Error: Unknown function '{fn_name}'."

            # Add the tool response to conversation
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result_str
            })

        # 3) Re-call the model for final answer
        second_resp = run_openai_chat(model_name, messages, openai_params)
        if second_resp["success"]:
            final_answer = second_resp["result"]["response"]
        else:
            final_answer = second_resp["result"]["response"]

    # For the "pp" scenario, prepend the size text
    if question.startswith("pp"):
        final_answer = f"Your penis size is {penis_size} inches. {final_answer}"

    # Store the conversation
    CONVERSATION_HISTORY.append({"role": "user", "content": question})
    CONVERSATION_HISTORY.append({"role": "assistant", "content": final_answer})

    # Banned-word censorship
    sanitized_answer = final_answer
    for banned in BANNED_WORDS:
        pattern = re.compile(rf"\b{re.escape(banned)}\b", re.IGNORECASE)
        sanitized_answer = pattern.sub("boob", sanitized_answer)

    # Finally, truncate to 400 chars & remove some disallowed characters
    sanitized_answer = sanitized_answer.strip()[:400]
    for char in ['{', '}', '"']:
        sanitized_answer = sanitized_answer.replace(char, '')

    return Response(sanitized_answer, 200, mimetype="text/plain; charset=utf-8")


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
