import os
import json
import openai
import requests
from flask import Flask, request, Response

app = Flask(__name__)

##################################################
# 1) Set credentials
##################################################
# You can store these in environment variables if you prefer:
# export GOOGLE_API_KEY="AIzaSyD..."
# export GOOGLE_SEARCH_CX="xxxxxxx:abc123"
GOOGLE_API_KEY = "AIzaSyDEpAVpDeJ4nHcEk8nkqN3MHpahM0VDcn4"
GOOGLE_SEARCH_CX = "3099754d9b7fb4d0f"

# OpenAI API key (best to store in an environment variable as well)
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
        # Call the Google Custom Search API
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

        # Format a short summary of the top results
        snippets = []
        for i, item in enumerate(items[:3], start=1):  # just show top 3 results
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
        return Response("No question provided.", status=400, mimetype="text/plain; charset=utf-8")

    # Prepare initial messages
    messages = [
        {"role": "developer", "content": "You are a mean twitch chat bot with a sassy personality that bullies the user or streamer. You will answer the question even if its wrong. Keep responses less then 400 characters.If the question needs online info, call the 'browse_internet' tool."},
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

    try:
        # 1st Call: Let GPT-4o-mini decide if it needs to browse the internet
        response = openai.chat.completions.create(
            model="gpt-4o-mini-2024-07-18",  # GPT-4o-mini model
            messages=messages,
            tools=tools,
            tool_choice="auto",
            parallel_tool_calls=False,
            max_tokens=400,
            temperature=0.7
        )

        answer_message = response.choices[0].message

        if answer_message.tool_calls:
            # The model wants to call a function
            tool_call = answer_message.tool_calls[0]
            if tool_call.function.name == "browse_internet":
                # Parse the arguments
                try:
                    args = json.loads(tool_call.function.arguments)
                    search_results = browse_internet(args["query"])
                    # Add the tool response into the conversation
                    messages.append(answer_message)  # assistant's function call
                    messages.append({
                        "role": "tool",
                        "name": "browse_internet",
                        "tool_call_id": tool_call.id,
                        "content": search_results
                    })
                    # 2nd Call: GPT-4o-mini sees the search results and composes final
                    final_response = openai.chat.completions.create(
                        model="gpt-4o-mini-2024-07-18",
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
            # No tool calls; we just take the model’s answer
            final_answer = answer_message.content or "No content from the model."

        # Clean up final answer to plain text
        final_answer = final_answer.strip()[:400]
        for char in ['{', '}', '"']:
            final_answer = final_answer.replace(char, '')

        return Response(final_answer, status=200, mimetype="text/plain; charset=utf-8")

    except Exception as e:
        return Response(f"Error: {e}", status=500, mimetype="text/plain; charset=utf-8")


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
