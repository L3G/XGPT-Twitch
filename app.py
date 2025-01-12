import os
import json
import openai
import requests
from flask import Flask, request, Response

app = Flask(__name__)

##################################################
# Global conversation history
##################################################
CONVERSATION_HISTORY = []

##################################################
# 1) Set credentials
##################################################
GOOGLE_API_KEY = "AIzaSyD..."
GOOGLE_SEARCH_CX = "3099754d9b7fb4d0f"
openai.api_key = os.getenv("OPENAI_API_KEY", "YOUR_OPENAI_API_KEY")

##################################################
# 2) Actual browse_internet function
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
            # Return an error message (still 200 in final response)
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
            # Keep in mind your prompt says "Do NOT include links in your response."
            # So we won't show them, just the snippet.
            snippets.append(f"Result {i}: {title}\nSnippet: {snippet}")

        return "\n\n".join(snippets)
    except Exception as e:
        return f"Error performing Google search: {str(e)}"

##################################################
# 3) Minimal Flask app that uses GPT-4o-mini
##################################################
@app.route('/answer', methods=['GET'])
def answer():
    question = request.args.get('question', '').strip()

    # Because StreamElements only shows output if the status is 200,
    # we'll ALWAYS return 200, even if the user didn't provide a question.
    # We'll just return some message in plain text.
    if not question:
        return Response(
            "No question provided. Usage: ?question=Your+Message+Here",
            200,  # 200 so StreamElements displays it
            mimetype="text/plain; charset=utf-8"
        )

    # Keep the last 4 messages (2 user–assistant turns)
    global CONVERSATION_HISTORY
    CONVERSATION_HISTORY = CONVERSATION_HISTORY[-4:]

    # Developer/system message
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

    # Build the messages array
    messages = [dev_message] + CONVERSATION_HISTORY + [
        {"role": "user", "content": question}
    ]

    # Define the single "browse_internet" tool
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
        # First call to GPT
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
        # Return 200 with the error text (so StreamElements can display it)
        return Response(f"OpenAI error: {e}", 200, mimetype="text/plain; charset=utf-8")

    answer_message = response.choices[0].message

    # Check if GPT wants to call the function
    if answer_message.tool_calls:
        tool_call = answer_message.tool_calls[0]
        if tool_call.function.name == "browse_internet":
            try:
                args = json.loads(tool_call.function.arguments)
                search_results = browse_internet(args["query"])

                # Insert the tool response
                messages.append(answer_message)  # The assistant's function call
                messages.append({
                    "role": "tool",
                    "name": "browse_internet",
                    "tool_call_id": tool_call.id,
                    "content": search_results
                })

                # Second call to GPT, now with the search results
                try:
                    final_response = openai.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=messages,
                        max_tokens=100,
                        temperature=0.7
                    )
                    final_answer = final_response.choices[0].message.content
                except Exception as e:
                    final_answer = f"OpenAI error (2nd call): {e}"

            except Exception as e:
                final_answer = f"Error parsing function arguments: {str(e)}"
        else:
            final_answer = "Tool called, but not recognized."
    else:
        # No function call
        final_answer = answer_message.content or "No content from the model."

    # Store the conversation
    CONVERSATION_HISTORY.append({"role": "user", "content": question})
    CONVERSATION_HISTORY.append({"role": "assistant", "content": final_answer})

    # Truncate to 400 chars & remove certain chars for plain text
    final_answer = final_answer.strip()[:400]
    for char in ['{', '}', '"']:
        final_answer = final_answer.replace(char, '')

    # Return 200 OK so StreamElements can parse it
    return Response(final_answer, 200, mimetype="text/plain; charset=utf-8")


if __name__ == '__main__':
    # Run on port 5000
    app.run(host='0.0.0.0', port=5000)