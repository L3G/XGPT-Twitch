import os
import json
import openai
import requests
from flask import Flask, request, Response

app = Flask(__name__)

##################################################
# Global conversation history
# We'll store pairs of user/assistant messages in memory
##################################################
CONVERSATION_HISTORY = []

##################################################
# 1) Set credentials
##################################################
GOOGLE_API_KEY = "AIzaSyD..."
GOOGLE_SEARCH_CX = "3099754d9b7fb4d0f"
openai.api_key = os.getenv("OPENAI_API_KEY", "YOUR_OPENAI_API_KEY")

##################################################
# 2) Actual browse_internet function using Google
##################################################
def browse_internet(search_query: str) -> str:
    """
    Makes a real request to the Google Custom Search API and
    returns a short string describing the top results.
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
            link = item.get("link", "")
            snippet = item.get("snippet", "")
            snippets.append(f"Result {i}: {title}\nLink: {link}\nSnippet: {snippet}")
        return "\n\n".join(snippets)
    except Exception as e:
        return f"Error performing Google search: {str(e)}"

##################################################
# 3) Minimal Flask app that uses GPT-4o-mini
##################################################
@app.route('/answer', methods=['GET'])
def answer():
    question = request.args.get('question', '').strip()
    if not question:
        return Response("No question provided.", 400, mimetype="text/plain; charset=utf-8")

    # 1) Build conversation context from global history
    # We'll keep the last few user–assistant turns
    # (2 messages = 1 user turn + 1 assistant turn)
    # Here we keep up to 4 messages = 2 user turns + 2 assistant turns
    global CONVERSATION_HISTORY
    # Only keep the last 4 messages to avoid indefinite growth
    CONVERSATION_HISTORY = CONVERSATION_HISTORY[-4:]

    # Start with a developer message
    dev_message = {
        "role": "developer",
        "content": (
            "You are a twitch chat bot with a sassy personality. If necessary you can "
            "be mean to the user or streamer and bully them. You will answer the question "
            "even if it's wrong. Keep responses less than 400 characters. "
            "Do NOT include any links in your response. If the question needs online info, "
            "call the 'browse_internet' tool but only call it once."
        )
    }

    # Our conversation so far: developer message + stored history + the new user question
    messages = [dev_message] + CONVERSATION_HISTORY + [
        {"role": "user", "content": question}
    ]

    # Define the tool
    tools = [
        {
            "type": "function",
            "function": {
                "name": "browse_internet",
                "description": "Use this to browse the internet if needed to answer the question.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The text to search on the internet."
                        }
                    },
                    "required": ["query"],
                    "additionalProperties": False
                }
            }
        }
    ]

    # 2) Let GPT-4o-mini decide if it needs to browse the internet
    try:
        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=tools,
            tool_choice="auto",
            parallel_tool_calls=False,
            max_tokens=400,
            temperature=0.7
        )
    except Exception as e:
        return Response(f"OpenAI error: {e}", 500, mimetype="text/plain; charset=utf-8")

    answer_message = response.choices[0].message

    # 3) Check if GPT called our function
    if answer_message.tool_calls:
        tool_call = answer_message.tool_calls[0]
        if tool_call.function.name == "browse_internet":
            try:
                args = json.loads(tool_call.function.arguments)
                search_results = browse_internet(args["query"])
                # Insert the tool response
                messages.append(answer_message)  # the assistant's function call
                messages.append({
                    "role": "tool",
                    "name": "browse_internet",
                    "tool_call_id": tool_call.id,
                    "content": search_results
                })
                # 2nd call for final answer
                final_response = openai.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                    max_tokens=100,
                    temperature=0.7
                )
                final_answer = final_response.choices[0].message.content
            except Exception as e:
                final_answer = f"Error parsing function arguments: {str(e)}"
        else:
            final_answer = "Tool called, but not recognized."
    else:
        # No tool calls
        final_answer = answer_message.content or "No content from the model."

    # 4) Save the user's question & final answer into the global conversation
    # so we can remember them next time.
    CONVERSATION_HISTORY.append({"role": "user", "content": question})
    CONVERSATION_HISTORY.append({"role": "assistant", "content": final_answer})

    # 5) Clean up final answer to plain text
    final_answer = final_answer.strip()[:400]
    for char in ['{', '}', '"']:
        final_answer = final_answer.replace(char, '')

    return Response(final_answer, 200, mimetype="text/plain; charset=utf-8")


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
